```python
# publish.py -- routes clean vs captioned per CAPTION_MODE config
import os
from config import CAPTION_MODE, get_next_optimal_time, AUTO_PUBLISH
from tiktok_publish    import upload_to_tiktok
from youtube_publish   import upload_to_youtube
from instagram_publish import upload_to_instagram
from drive import make_public_url


def publish_all(outputs, srt_path, script_data, account_type):
    title   = script_data["title"]
    caption = _build_caption(script_data, account_type)
    tags    = _build_tags(account_type)

    # TikTok -- clean video, native captions
    if AUTO_PUBLISH.get("tiktok", False):
        tiktok_file = outputs["clean"]["path"] if CAPTION_MODE["tiktok"] == "native" else outputs["captioned"]["path"]
        upload_to_tiktok(tiktok_file, caption)
        print("TikTok: uploaded clean video -- native captions will be generated")
    else:
        print("TikTok: auto-publish disabled -- video saved to Drive/07_final/")

    # YouTube -- clean video + SRT sidecar
    if AUTO_PUBLISH.get("youtube", False):
        yt_file = outputs["clean"]["path"] if CAPTION_MODE["youtube"] == "native" else outputs["captioned"]["path"]
        upload_to_youtube(yt_file, title, caption, tags, srt_path)
        print("YouTube: uploaded clean video + SRT sidecar for indexed captions")
    else:
        print("YouTube: auto-publish disabled -- video saved to Drive/07_final/")

    # YouTube Shorts -- trimmed version, separate upload with Shorts-specific SRT
    if AUTO_PUBLISH.get("youtube", False) and outputs.get("shorts"):
        shorts_title   = script_data.get("title", title) + " #Shorts"
        shorts_caption = _build_caption(script_data, account_type) + " #Shorts"
        shorts_srt     = outputs["shorts"].get("srt_path", srt_path)
        upload_to_youtube(
            outputs["shorts"]["path"],
            shorts_title,
            shorts_caption,
            tags + ["Shorts", "YouTubeShorts"],
            shorts_srt,
        )
        print("YouTube Shorts: uploaded trimmed Shorts cut")
    elif outputs.get("shorts"):
        print("YouTube Shorts: auto-publish disabled -- Shorts cut saved to Drive/07_final/")
    else:
        print("YouTube Shorts: no Shorts cut available -- skipping")

    # Instagram -- captioned video via temporary public Drive URL
    if AUTO_PUBLISH.get("instagram", False):
        ig_drive_id = outputs["captioned"]["drive_id"]
        public_url  = make_public_url(ig_drive_id)
        upload_to_instagram(public_url, caption)
        print("Instagram: uploaded captioned video with baked-in captions")
    else:
        print("Instagram: auto-publish disabled -- video saved to Drive/07_final/")


def _build_caption(script_data, account_type):
    title = script_data["title"]
    if account_type == "history":
        return title + " #history #learnontiktok #historyfacts #didyouknow"
    return title + " #news #explained #context #learnontiktok #currentevents"


def _build_tags(account_type):
    base = ["explained", "learnontiktok", "education", "context"]
    if account_type == "history":
        return base + ["history", "historyfacts", "historylesson"]
    return base + ["news", "currentevents", "nonpartisan"]
```