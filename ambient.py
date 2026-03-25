# ambient.py -- per-scene ambient sound search and download
# Uses Freesound API with CC0 filter only -- no attribution required
import requests, os, subprocess, json
from dotenv import load_dotenv
from config import TMP

load_dotenv()

FREESOUND_KEY  = os.getenv("FREESOUND_API_KEY")
FREESOUND_URL  = "https://freesound.org/apiv2/search/text/"
AMBIENT_VOLUME = "0.08"   # -22db under VO -- barely perceptible, adds presence only


def search_freesound(query, duration_max=30):
    if not FREESOUND_KEY:
        print("  WARNING: FREESOUND_API_KEY not set -- skipping ambient search")
        return None, None
    params = {
        "query":      query,
        "license":    "Creative Commons 0",
        "fields":     "id,name,duration,previews",
        "filter":     f"duration:[1 TO {duration_max}]",
        "sort":       "score",
        "page_size":  5,
        "token":      FREESOUND_KEY,
    }
    try:
        r = requests.get(FREESOUND_URL, params=params, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            print(f"  No CC0 ambient found for: {query}")
            return None, None
        best        = results[0]
        preview_url = best["previews"]["preview-hq-mp3"]
        duration    = best["duration"]
        print(f"  Ambient found: '{best['name']}' ({duration:.1f}s)")
        return preview_url, duration
    except Exception as e:
        print(f"  Freesound search failed: {e}")
        return None, None


def download_ambient(url, scene_num, slug):
    slug_dir  = os.path.join(TMP, slug)
    os.makedirs(slug_dir, exist_ok=True)
    local_mp3 = os.path.join(slug_dir, f"ambient_{scene_num:02d}.mp3")
    try:
        data = requests.get(url, timeout=30).content
        with open(local_mp3, "wb") as f:
            f.write(data)
        return local_mp3
    except Exception as e:
        print(f"  Ambient download failed: {e}")
        return None


def trim_ambient_to_clip(ambient_path, clip_duration, scene_num, slug):
    slug_dir     = os.path.join(TMP, slug)
    trimmed_path = os.path.join(slug_dir, f"ambient_trimmed_{scene_num:02d}.mp3")
    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", ambient_path,
            "-t", str(clip_duration),
            "-af", "afade=t=in:st=0:d=0.5,afade=t=out:st=" + str(max(0, clip_duration - 0.5)) + ":d=0.5",
            trimmed_path
        ], check=True, capture_output=True)
        return trimmed_path
    except Exception as e:
        print(f"  Ambient trim failed: {e}")
        return None


def get_ambient_for_scenes(scenes, clip_paths, slug):
    ambient_paths = []
    for i, scene in enumerate(scenes):
        if isinstance(scene, dict):
            ambient_query = scene.get("ambient", "")
        else:
            ambient_query = ""
        if not ambient_query:
            print(f"  Scene {i+1}: no ambient field -- skipping")
            ambient_paths.append(None)
            continue
        print(f"  Scene {i+1}: searching for '{ambient_query}'")
        clip_path     = clip_paths[i]["path"] if i < len(clip_paths) else None
        clip_duration = 5.0
        if clip_path and os.path.exists(clip_path):
            try:
                result = subprocess.run([
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_streams", clip_path
                ], capture_output=True, text=True)
                clip_duration = float(
                    json.loads(result.stdout)["streams"][0]["duration"]
                )
            except Exception:
                pass
        url, _ = search_freesound(ambient_query, duration_max=30)
        if not url:
            ambient_paths.append(None)
            continue
        mp3_path = download_ambient(url, i, slug)
        if not mp3_path:
            ambient_paths.append(None)
            continue
        trimmed = trim_ambient_to_clip(mp3_path, clip_duration, i, slug)
        ambient_paths.append(trimmed)
    found = sum(1 for p in ambient_paths if p is not None)
    print(f"  Ambient ready: {found}/{len(scenes)} scenes")
    return ambient_paths