# main.py -- three-phase pipeline with file-watcher trigger support
import sys, datetime, traceback, argparse
from config  import get_style, is_home_day
from discover import run_scan
from script   import run_scripting
from images   import run_image_generation
from clips    import run_clip_generation
from audio    import run_audio
from assemble import assemble_video, assemble_silent_preview
from publish  import publish_all
from sheets   import log_job, save_todays_script, load_todays_script, load_todays_clips, save_todays_clips
from notify   import send_notification

def run_phase1(account_type="history"):
    """Script generation. Runs on schedule or when scanner threshold is met."""
    job = {"phase": "1", "account": account_type}
    try:
        candidates = run_scan()
        script_data, fid = run_scripting(candidates, account_type)
        save_todays_script(script_data, account_type)
        job.update({"title": script_data["title"], "status": "success"})
        send_notification(
            title   = f"Script ready: {script_data['title']}",
            message = (f"{script_data['script'][:300]}...\n\n"
                       "Visuals generating now (~2hrs).\n"
                       "Will notify when preview is ready to watch."),
            priority = "normal")
    except Exception:
        job.update({"status": "error", "error": traceback.format_exc()})
    finally:
        log_job(account_type, "phase1", status=job.get("status", "error"))

def run_phase2(account_type="history"):
    """Images + clips + silent preview. Runs immediately after Phase 1."""
    job = {"phase": "2", "account": account_type}
    try:
        script_data = load_todays_script(account_type)
        image_paths = run_image_generation(script_data, get_style(account_type))
        clip_paths  = run_clip_generation(image_paths, account_type)
        save_todays_clips(clip_paths, account_type)
        preview = assemble_silent_preview(clip_paths, script_data["title"])
        from drive import upload_file
        upload_file(preview, "previews")
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
        log_job(account_type, "phase2", status=job.get("status", "error"))

def run_phase3(account_type="history", trigger="cron"):
    """Audio + assembly + publish. Triggered by file watcher or fallback cron."""
    job = {"phase": "3", "account": account_type, "trigger": trigger}
    try:
        script_data = load_todays_script(account_type)
        clip_paths  = load_todays_clips(account_type)
        if trigger == "file_watcher":
            send_notification(
                title="Recording detected -- production starting",
                message=f"Building final video: {script_data['title']}\nReady in ~15 minutes.",
                priority="normal")
        audio_path, srt_path = run_audio(script_data, account_type)
        outputs = assemble_video(clip_paths, audio_path, srt_path, script_data["title"])
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
        log_job(account_type, "phase3", status=job.get("status", "error"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["1", "2", "3", "breaking", "recap"])
    parser.add_argument("account", nargs="?", default="history")
    parser.add_argument("--trigger", default="cron")
    args = parser.parse_args()

    if   args.phase == "1":        run_phase1(args.account)
    elif args.phase == "2":        run_phase2(args.account)
    elif args.phase == "3":        run_phase3(args.account, args.trigger)
    elif args.phase == "breaking": from breaking import run_breaking; run_breaking()
    elif args.phase == "recap":    from recap import run_weekly_recap; run_weekly_recap()
