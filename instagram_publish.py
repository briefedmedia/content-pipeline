# instagram_publish.py -- Instagram Graph API
# Docs: https://developers.facebook.com/docs/instagram-api/guides/content-publishing
# Requires: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_ACCOUNT_ID in .env
# Apply at: https://developers.facebook.com -- create app, add Instagram product

import os, requests, time
from dotenv import load_dotenv
load_dotenv()

IG_TOKEN      = os.getenv("INSTAGRAM_ACCESS_TOKEN")
IG_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID")
IG_API        = "https://graph.facebook.com/v19.0"


def upload_to_instagram(public_video_url, caption):
    if not all([IG_TOKEN, IG_ACCOUNT_ID]):
        print("  Instagram: credentials not set -- skipping")
        return None

    print(f"  Instagram: creating media container...")

    # Step 1 -- create media container
    container_resp = requests.post(
        f"{IG_API}/{IG_ACCOUNT_ID}/media",
        params={
            "media_type":  "REELS",
            "video_url":   public_video_url,
            "caption":     caption[:2200],
            "access_token": IG_TOKEN,
        },
    )
    container_resp.raise_for_status()
    container_id = container_resp.json()["id"]
    print(f"  Instagram: container created (id: {container_id})")

    # Step 2 -- wait for container to finish processing
    for attempt in range(12):  # max 2 minutes
        time.sleep(10)
        status_resp = requests.get(
            f"{IG_API}/{container_id}",
            params={
                "fields":       "status_code",
                "access_token": IG_TOKEN,
            },
        )
        status = status_resp.json().get("status_code")
        print(f"  Instagram: container status: {status}")
        if status == "FINISHED":
            break
        elif status == "ERROR":
            raise Exception(f"Instagram container processing failed")
    else:
        raise Exception("Instagram container timed out after 2 minutes")

    # Step 3 -- publish
    publish_resp = requests.post(
        f"{IG_API}/{IG_ACCOUNT_ID}/media_publish",
        params={
            "creation_id":  container_id,
            "access_token": IG_TOKEN,
        },
    )
    publish_resp.raise_for_status()
    media_id = publish_resp.json()["id"]
    print(f"  Instagram: published (media_id: {media_id})")
    return media_id
```

Add these to `.env` when you get API access — leave them empty for now:
```
TIKTOK_ACCESS_TOKEN=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
INSTAGRAM_ACCESS_TOKEN=
INSTAGRAM_ACCOUNT_ID=