# clips.py -- video clip generation
# Supports Runway Gen-3 and Pika v2.2 via fal.ai
# Toggle between them in config.py: VIDEO_GENERATOR = 'pika' or 'runway'
# Per-account override also supported in config.py

import requests
import time
import os
import base64
import datetime
import fal_client
from dotenv import load_dotenv
from drive import upload_file
from config import get_generator

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
            'image_url':  image_url,
            'prompt':     motion_prompt,
            'resolution': '1080p',
            'duration':   duration,
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


def download_and_upload_clip(video_url, clip_num, today):
    """Download the generated clip and upload to Google Drive."""
    data = requests.get(video_url).content
    local_path = f'/tmp/clip_{today}_{clip_num:02d}.mp4'

    with open(local_path, 'wb') as f:
        f.write(data)

    file_id = upload_file(local_path, 'clips')
    return local_path, file_id


# ── Main entry point ───────────────────────────────────────────────────────────

def run_clip_generation(image_paths, account_type='history'):
    """
    Generate one video clip per image.
    Motion prompts rotate through the brand-compliant list for the account type.
    Generator (Runway vs Pika) is determined by config.py.
    """
    today   = datetime.date.today().isoformat()
    prompts = MOTION_PROMPTS.get(account_type, MOTION_PROMPTS['news'])
    generator = get_generator(account_type)

    clip_paths = []

    for i, img in enumerate(image_paths):
        motion = prompts[i % len(prompts)]

        print(f'Generating clip {i+1}/{len(image_paths)} via {generator}...')
        print(f'  Motion: {motion[:60]}...')

        video_url = generate_clip(img['path'], motion, 5, account_type)
        path, fid = download_and_upload_clip(video_url, i, today)

        clip_paths.append({'path': path, 'drive_id': fid})
        print(f'  Clip {i+1} saved: {path}')

    print(f'Generated {len(clip_paths)} clips via {generator}')
    return clip_paths