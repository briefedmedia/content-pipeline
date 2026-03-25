# tiktok_publish.py -- TikTok Content Posting API v2
# Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
# Requires: TIKTOK_ACCESS_TOKEN in .env
# Apply at: https://developers.tiktok.com

import os, requests
from dotenv import load_dotenv
load_dotenv()

TIKTOK_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN")
TIKTOK_API   = "https://open.tiktokapis.com/v2"

def upload_to_tiktok(video_path, caption):
    if not TIKTOK_TOKEN:
        print("  TikTok: TIKTOK_ACCESS_TOKEN not set -- skipping")
        return None

    print(f"  TikTok: uploading {os.path.basename(video_path)}...")

    # Step 1 -- initialize upload
    init_resp = requests.post(
        f"{TIKTOK_API}/post/publish/video/init/",
        headers={
            "Authorization": f"Bearer {TIKTOK_TOKEN}",
            "Content-Type":  "application/json; charset=UTF-8",
        },
        json={
            "post_info": {
                "title":        caption[:2200],  # TikTok cap
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "disable_duet":  False,
                "disable_stitch": False,
                "disable_comment": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source":          "FILE_UPLOAD",
                "video_size":      os.path.getsize(video_path),
                "chunk_size":      os.path.getsize(video_path),
                "total_chunk_count": 1,
            },
        },
    )
    init_resp.raise_for_status()
    init_data   = init_resp.json()
    publish_id  = init_data["data"]["publish_id"]
    upload_url  = init_data["data"]["upload_url"]

    # Step 2 -- upload video bytes
    with open(video_path, "rb") as f:
        video_bytes = f.read()
    upload_resp = requests.put(
        upload_url,
        headers={
            "Content-Type":   "video/mp4",
            "Content-Range":  f"bytes 0-{len(video_bytes)-1}/{len(video_bytes)}",
            "Content-Length": str(len(video_bytes)),
        },
        data=video_bytes,
    )
    upload_resp.raise_for_status()

    print(f"  TikTok: upload complete (publish_id: {publish_id})")
    return publish_id