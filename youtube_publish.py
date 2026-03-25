# youtube_publish.py -- YouTube Data API v3
# Docs: https://developers.google.com/youtube/v3/guides/uploading_a_video
# Requires: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN in .env
# Apply at: https://console.cloud.google.com -- enable YouTube Data API v3

import os, requests
from dotenv import load_dotenv
load_dotenv()

YT_CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID")
YT_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN")
YT_API           = "https://www.googleapis.com/upload/youtube/v3"
YT_TOKEN_URL     = "https://oauth2.googleapis.com/token"


def _get_access_token():
    resp = requests.post(YT_TOKEN_URL, data={
        "client_id":     YT_CLIENT_ID,
        "client_secret": YT_CLIENT_SECRET,
        "refresh_token": YT_REFRESH_TOKEN,
        "grant_type":    "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def upload_to_youtube(video_path, title, description, tags, srt_path=None):
    if not all([YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN]):
        print("  YouTube: credentials not set -- skipping")
        return None

    print(f"  YouTube: uploading {os.path.basename(video_path)}...")
    token = _get_access_token()

    # Upload video
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    upload_resp = requests.post(
        f"{YT_API}/videos",
        params={"uploadType": "multipart", "part": "snippet,status"},
        headers={"Authorization": f"Bearer {token}"},
        json={
            "snippet": {
                "title":       title[:100],
                "description": description[:5000],
                "tags":        tags,
                "categoryId":  "25",  # News & Politics
            },
            "status": {
                "privacyStatus":           "public",
                "selfDeclaredMadeForKids": False,
            },
        },
    )
    upload_resp.raise_for_status()
    video_id = upload_resp.json()["id"]
    print(f"  YouTube: video uploaded (id: {video_id})")

    # Upload SRT captions if provided
    if srt_path and os.path.exists(srt_path):
        with open(srt_path, "rb") as f:
            srt_bytes = f.read()
        cap_resp = requests.post(
            f"{YT_API}/captions",
            params={"uploadType": "multipart", "part": "snippet"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "snippet": {
                    "videoId":   video_id,
                    "language":  "en",
                    "name":      "English",
                    "isDraft":   False,
                },
            },
        )
        if cap_resp.ok:
            print(f"  YouTube: captions uploaded")
        else:
            print(f"  YouTube: caption upload failed -- {cap_resp.text}")

    return video_id