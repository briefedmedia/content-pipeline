# clips.py -- video clip generation
# Supports Runway Gen-3 and Pika v2.2 via fal.ai
# Toggle between them in config.py: VIDEO_GENERATOR = 'pika' or 'runway'
# Per-account override also supported in config.py

import requests
import time
import os
import base64
import datetime
from dotenv import load_dotenv
load_dotenv()
from config import get_generator, TMP
from drive import upload_file, get_or_create_story_folder
import fal_client

load_dotenv()

# Runway setup
RUNWAY_API_KEY = os.getenv('RUNWAY_API_KEY')
RUNWAY_BASE    = 'https://api.dev.runwayml.com/v1'

# fal.ai / Pika setup
# FAL_KEY is read automatically by fal_client from environment
# Make sure FAL_KEY is in your .env file -- NOT PIKA_API_KEY


# Brand-compliant motion prompts from brand guide
# History: atmospheric, cinematic restraint
# News: clean, professional motion graphics
MOTION_PROMPTS = {
    'history': [
        'Slow, barely perceptible push toward subject. Atmospheric still. Held breath. No camera shake.',
        'Extremely slow horizontal drift. 35mm documentary cinematography. Shallow depth of field. Motivated side lighting.',
        'Absolutely static frame. Dust particles. Light rays through window. No movement except atmosphere.',
        'Subtle rack focus suggestion. Still subject. Slight environmental movement only -- candlelight, fabric, hair.',
        'Slow horizontal pan. 1-2% zoom over full clip. Fog or atmospheric haze. Documentary wide lens.',
    ],
    'news': [
        'Subtle scale animation. Clean motion graphics aesthetic. Professional broadcast quality. No camera movement.',
        'Clean reveal motion. Smooth and deliberate. Information design animation quality.',
        'Slow push in. Clean documentary style. Steady professional cinematography.',
        'Minimal atmospheric movement. Professional motion graphics. Still and considered.',
    ],
}


# ── Runway implementation ──────────────────────────────────────────────────────

def _generate_runway(image_path, motion_prompt, duration=5):
    """Generate a clip using Runway Gen-3 Turbo API."""
    with open(image_path, 'rb') as f:
        b64 = 'data:image/png;base64,' + base64.b64encode(f.read()).decode()

    headers = {
        'Authorization': f'Bearer {RUNWAY_API_KEY}',
        'Content-Type': 'application/json',
        'X-Runway-Version': '2024-11-06',
    }

    payload = {
        'model':       'gen3a_turbo',
        'promptImage': b64,
        'promptText':  motion_prompt,
        'duration':    duration,
        'ratio':       '768:1344',   # 9:16 vertical
    }

    r = requests.post(
        f'{RUNWAY_BASE}/image_to_video',
        json=payload,
        headers=headers
    )
    r.raise_for_status()
    task_id = r.json()['id']

    # Poll until complete
    while True:
        time.sleep(10)
        status = requests.get(
            f'{RUNWAY_BASE}/tasks/{task_id}',
            headers=headers
        ).json()

        if status['status'] == 'SUCCEEDED':
            return status['output'][0]
        elif status['status'] == 'FAILED':
            raise Exception(f'Runway generation failed: {status}')


# ── Pika via fal.ai implementation ────────────────────────────────────────────

def _generate_pika(image_path, motion_prompt, duration=5):
    """
    Generate a clip using Pika v2.2 image-to-video via fal.ai.

    fal_client automatically reads FAL_KEY from environment.
    It uploads the local image file to fal's CDN, then submits
    the generation job and waits for completion.
    """

    # Step 1: Upload local image to fal's CDN
    # fal requires a public URL -- upload_file handles this
    print(f'  Uploading image to fal CDN...')
    image_url = fal_client.upload_file(image_path)

    # Step 2: Submit generation and wait for result
    def on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs:
                print(f'  Pika: {log["message"]}')

    result = fal_client.subscribe(
        'fal-ai/pika/v2.2/image-to-video',   # correct model ID
        arguments={
            'image_url':       image_url,
            'prompt':          motion_prompt,
            'resolution':      '1080p',
            'aspect_ratio':    '9:16',
            'duration':        duration,
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )

    # Step 3: Return video URL
    return result['video']['url']


# ── Shared dispatcher ──────────────────────────────────────────────────────────

def generate_clip(image_path, motion_prompt, duration, account_type):
    """Route to Runway or Pika based on config."""
    generator = get_generator(account_type)

    if generator == 'runway':
        return _generate_runway(image_path, motion_prompt, duration)
    elif generator == 'pika':
        return _generate_pika(image_path, motion_prompt, duration)
    else:
        raise ValueError(f'Unknown generator: {generator}')


def download_and_upload_clip(video_url, clip_num, slug, clips_folder_id,
                             section="", visual_label=""):
    """Download a generated clip and upload it into the story's Drive subfolder."""
    data = requests.get(video_url).content

    # Mirror image semantic naming; fallback to old convention for legacy scripts
    if section and visual_label:
        filename = f"{clip_num+1:02d}_{section}_{visual_label}.mp4"
    else:
        filename = f"clip_{slug}_{clip_num:02d}.mp4"

    local_path = os.path.join(TMP, slug, filename)
    with open(local_path, 'wb') as f:
        f.write(data)

    file_id = upload_file(local_path, 'clips', folder_id=clips_folder_id)
    return local_path, file_id


# ── Main entry point ───────────────────────────────────────────────────────────

def run_clip_generation(image_paths, account_type='history', tracker=None):
    """
    Generate one video clip per image.
    Slug is read from image_paths[0]['slug'] -- set by images.py, never regenerated.
    Motion prompts rotate through the brand-compliant list for the account type.
    Generator (Runway vs Pika) is determined by config.py.
    """
    # Slug flows from images.py -- single source of truth
    slug      = image_paths[0]['slug'] if image_paths else datetime.date.today().isoformat() + '_story'
    prompts   = MOTION_PROMPTS.get(account_type, MOTION_PROMPTS['news'])
    generator = get_generator(account_type)

    # Ensure local slug subfolder exists (images.py already created it, but be safe)
    os.makedirs(os.path.join(TMP, slug), exist_ok=True)

    # Find or create the story subfolder in Drive/clips/
    clips_folder_id = get_or_create_story_folder(slug, 'clips')

    clip_paths = []

    for i, img in enumerate(image_paths):
        # Prefer the per-scene motion directive written by Claude in script.py.
        # Fall back to the rotating MOTION_PROMPTS list only for old scripts that
        # lack the motion field (flat-string scene format).
        per_scene = img.get("motion", "").strip()
        if per_scene:
            motion     = per_scene
            motion_src = "per-scene directive"
        else:
            motion     = prompts[i % len(prompts)]
            motion_src = "fallback prompt"

        print(f'Generating clip {i+1}/{len(image_paths)} via {generator}...')
        print(f'  Motion ({motion_src}): {motion[:80]}...')

        section      = img.get("section", "")
        visual_label = img.get("visual_label", "")

        video_url = generate_clip(img['path'], motion, 5, account_type)
        path, fid = download_and_upload_clip(video_url, i, slug, clips_folder_id,
                                             section=section, visual_label=visual_label)
        if tracker:
            _gen = get_generator(account_type)
            _fal_endpoints = {
                'pika':  'fal-ai/pika/v2.2/image-to-video',
                'kling': 'fal-ai/kling-video/v2.5/turbo/image-to-video',
            }
            if _gen in _fal_endpoints:
                tracker.add_fal(i, _fal_endpoints[_gen], 5.0)

        clip_paths.append({'path': path, 'drive_id': fid, 'slug': slug})
        print(f'  Clip {i+1} saved: {path}')
        # Log granular progress to Sheets
        try:
            from sheets import log_job
            log_job("news", "2", status="running", note=f"clips={i+1}/{len(image_paths)}")
        except Exception:
            pass

    print(f'Generated {len(clip_paths)} clips via {generator} → Drive/clips/{slug}/')
    try:
        from sheets import log_job
        log_job("news", "2", status="running", note=f"clips_done={len(clip_paths)}")
    except Exception:
        pass
    return clip_paths

if __name__ == "__main__":
    import json, glob
    from config import TMP

    today   = datetime.date.today().isoformat()
    pattern = os.path.join(TMP, f"{today}_*", f"script_{today}_*.json")
    matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    if not matches:
        print(f"No script file found — run script.py first")
    else:
        with open(matches[0], encoding="utf-8") as f:
            script_data = json.load(f)

        slug     = script_data["slug"]
        slug_dir = os.path.join(TMP, slug)

        # Reconstruct image_paths from local files
        image_files = sorted(glob.glob(os.path.join(slug_dir, "scene_*.png")))
        if not image_files:
            print(f"No images found in {slug_dir} — run images.py first")
        else:
            scenes = script_data.get("scenes", [])
            image_paths = []
            for i, p in enumerate(image_files):
                scene = scenes[i] if i < len(scenes) else {}
                image_paths.append({
                    "path":     p,
                    "drive_id": None,
                    "scene":    scene.get("image", "") if isinstance(scene, dict) else scene,
                    "motion":   scene.get("motion", "") if isinstance(scene, dict) else "",
                    "slug":     slug,
                })
            print(f"Found {len(image_paths)} images for {slug}")
            print(f"Generator: {get_generator('news')}\n")

            # Test with first image only before running full set
            clip_paths = run_clip_generation(image_paths[:1], account_type="news")

            print(f"\nTest clip done: {clip_paths[0]['path']}")
            print(f"Drive ID: {clip_paths[0]['drive_id']}")
            print(f"If it looks good, change image_paths[:1] to image_paths")