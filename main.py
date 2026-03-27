# main.py -- three-phase pipeline with file-watcher trigger support
import sys, datetime, traceback, argparse, os
from config  import get_style, is_home_day, TMP
from discover import run_discovery
from script   import run_scripting
from images   import run_image_generation
from clips    import run_clip_generation
from audio    import run_audio
from assemble import assemble_video, assemble_silent_preview
from publish  import publish_all
from sheets   import log_job, save_todays_script, load_todays_script, load_todays_clips, save_todays_clips
from notify   import send_notification

def run_phase1(account_type="news"):
    """
    Phase 1 -- discovery only.
    Saves candidates to Drive and sends Pushover approval notification.
    Does NOT proceed to scripting -- waits for manual approval via tap links.
    Auto-selects story #1 after 2 hours if no response.
    """
    from discover import run_discovery
    from notify   import notify_stories_ready
    from config   import MIN_EXPLAINABILITY_SCORE
    import os, datetime

    candidates = run_discovery()

    qualified = [
        c for c in candidates
        if c.get("historical_context") and
        c["historical_context"].get("explainability_score", 0) >= MIN_EXPLAINABILITY_SCORE
    ]

    today      = datetime.date.today().isoformat()
    server_url = os.getenv("SERVER_URL", "https://your-app.railway.app")

    # discover.py already uploads candidates_{today}.json to Drive -- no re-upload needed

    notify_stories_ready(
        candidates          = qualified,
        date                = today,
        server_url          = server_url,
        auto_select_minutes = 120,
    )

    print(f"Phase 1 complete. {len(qualified)} stories sent for approval.")
    print(f"Auto-selects story #1 in 2 hours if no response.")
    log_job(account_type, "1", status="success")


def run_phase2_for_story(date, story_index, account_type="news"):
    """
    Phase 2 for a single approved story.
    Called by pipeline_api.py when approval tap link is hit.
    Runs: script generation + image generation + clip generation + silent preview.
    Sends Pushover notification when preview is ready for VO recording.
    """
    import json
    from script   import run_scripting
    from images   import run_image_generation
    from clips    import run_clip_generation
    from assemble import assemble_silent_preview
    from drive    import upload_file, get_or_create_story_folder, get_or_create_pending_story_folder
    from notify   import notify_preview_ready
    from config   import TMP, MIN_EXPLAINABILITY_SCORE

    # Load candidates -- from local TMP if available, otherwise download from Drive
    candidates_path = os.path.join(TMP, date, f"candidates_{date}.json")
    if not os.path.exists(candidates_path):
        # Not found locally -- download from Drive (Railway execution path)
        from drive import download_file, get_or_create_story_folder
        os.makedirs(os.path.join(TMP, date), exist_ok=True)
        folder_id = get_or_create_story_folder(date, "stories")
        from drive import get_service
        service = get_service()
        results = service.files().list(
            q=(f'"{folder_id}" in parents and '
               f'name = "candidates_{date}.json" and trashed = false'),
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = results.get("files", [])
        if not files:
            raise FileNotFoundError(
                f"candidates_{date}.json not found locally or in Drive. "
                f"Run Phase 1 first."
            )
        download_file(files[0]["id"], candidates_path)
        print(f"Downloaded candidates from Drive for {date}")

    with open(candidates_path, encoding="utf-8") as f:
        data = json.load(f)

    candidates = data["candidates"]

    qualified = [
        c for c in candidates
        if c.get("historical_context") and
        c["historical_context"].get("explainability_score", 0) >= MIN_EXPLAINABILITY_SCORE
    ]

    if story_index >= len(qualified):
        print(f"Story index {story_index} out of range ({len(qualified)} qualified)")
        return

    story            = qualified[story_index]
    script_data, fid = run_scripting([story], account_type)
    slug             = script_data["slug"]

    style       = "history_old" if account_type == "history" else "news"
    image_paths = run_image_generation(script_data, style)
    clip_paths  = run_clip_generation(image_paths, account_type)

    preview_path = assemble_silent_preview(clip_paths, script_data["title"], slug)
    previews_fid = get_or_create_story_folder(slug, "previews")
    upload_file(preview_path, "previews", folder_id=previews_fid)

    # Create VO drop zone in pending/
    pending_folder_id = get_or_create_pending_story_folder(slug)
    script_data["pending_folder_id"] = pending_folder_id

    slug_dir    = os.path.join(TMP, slug)
    drop_txt    = os.path.join(slug_dir, "DROP_VO_HERE.txt")
    vo_filename = f"voiceover_{slug}_{account_type}.mp3"
    with open(drop_txt, "w", encoding="utf-8") as f:
        f.write(
            f"{'='*54}\n"
            f"DROP YOUR VOICEOVER RECORDING INTO THIS FOLDER\n"
            f"{'='*54}\n\n"
            f"Story:    {script_data['title']}\n"
            f"Date:     {date}\n"
            f"Slug:     {slug}\n"
            f"Account:  {account_type}\n\n"
            f"Name your file exactly:\n"
            f"  {vo_filename}\n\n"
            f"The file watcher checks this folder every 60 seconds.\n"
            f"When it detects your recording, Phase 3 starts automatically.\n\n"
            f"Script preview:\n"
            f"{'─'*46}\n"
            f"{script_data['script'][:300]}...\n"
            f"{'─'*46}\n"
        )
    upload_file(drop_txt, "pending", folder_id=pending_folder_id)
    print(f"  VO drop zone created: Drive/pending/{slug}/")

    notify_preview_ready(script_data["title"], account_type,
                         preview_drive_path=f"Drive/previews/{slug}/")

    log_job(account_type, "2", status="success")

def run_phase2(account_type="history"):
    """Images + clips + silent preview. Runs immediately after Phase 1."""
    job = {"phase": "2", "account": account_type}
    try:
        script_data = load_todays_script(account_type)
        slug        = script_data["slug"]
        image_paths = run_image_generation(script_data, get_style(account_type))
        clip_paths  = run_clip_generation(image_paths, account_type)
        save_todays_clips(clip_paths, account_type)
        preview = assemble_silent_preview(clip_paths, script_data["title"], slug)
        from drive import upload_file, get_or_create_story_folder
        previews_fid = get_or_create_story_folder(slug, "previews")
        upload_file(preview, "previews", folder_id=previews_fid)
        job.update({"title": script_data["title"], "status": "success",
                    "clip_count": len(clip_paths), "phase2_status": "success"})
        send_notification(
            title   = f"Preview ready: {script_data['title']}",
            message = ("Your rough cut is in Drive/previews/\n"
                       "Watch it, record your VO, drop in Drive/05_audio/pending/\n"
                       "Pipeline starts automatically when it detects your file."),
            priority = "normal")
    except Exception:
        job.update({"status": "error", "error": traceback.format_exc()})
    finally:
        log_job(account_type, "2", status=job.get("status", "error"))

def run_phase3(account_type="history", trigger="cron", slug=None):
    """Audio + assembly + publish. Triggered by file watcher or fallback cron."""
    job = {"phase": "3", "account": account_type, "trigger": trigger}
    try:
        script_data = load_todays_script(account_type, slug=slug)
        slug        = script_data["slug"]
        clip_paths  = load_todays_clips(account_type, slug=slug)
        if trigger == "file_watcher":
            send_notification(
                title="Recording detected -- production starting",
                message=f"Building final video: {script_data['title']}\nReady in ~15 minutes.",
                priority="normal")
        audio_path, srt_path = run_audio(script_data, account_type)
        outputs = assemble_video(clip_paths, audio_path, srt_path, script_data["title"], slug)
        publish_all(outputs, srt_path, script_data, account_type)
        job.update({"title": script_data["title"], "status": "success",
                    "duration": outputs["duration"],
                    "clean_drive_id": outputs["clean"]["drive_id"],
                    "captioned_drive_id": outputs["captioned"]["drive_id"]})
        send_notification(
            title=f"Video ready: {script_data['title']}",
            message=f"Duration: {outputs['duration']:.0f}s\nScheduled to post at next optimal time.",
            priority="normal")
    except Exception:
        job.update({"status": "error", "error": traceback.format_exc()})
    finally:
        log_job(account_type, "3", status=job.get("status", "error"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["1", "2", "3", "breaking", "recap"])
    parser.add_argument("account", nargs="?", default="history")
    parser.add_argument("--trigger", default="cron")
    parser.add_argument("--slug",    default=None)
    args = parser.parse_args()

    if   args.phase == "1":        run_phase1(args.account)
    elif args.phase == "2":        run_phase2(args.account)
    elif args.phase == "3":        run_phase3(args.account, args.trigger, args.slug)
    elif args.phase == "breaking": from breaking import run_breaking; run_breaking()
    elif args.phase == "recap":    from recap import run_weekly_recap; run_weekly_recap()
