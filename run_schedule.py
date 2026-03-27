# run_schedule.py -- internal scheduler for Railway pipeline-cron service
# Polls Google Sheets job_queue worksheet for API-enqueued work
import schedule, time, os

def job(phase, account):
    cmd = f"python main.py {phase} {account}".strip()
    print(f"[Scheduler] Running: {cmd}")
    try:
        result = os.system(cmd)
        if result != 0:
            from notify import notify_error
            notify_error(phase, account or "news",
                         f"Exit code {result} — command: {cmd}")
            print(f"[Scheduler] WARNING: {cmd} exited with code {result}")
    except Exception as e:
        from notify import notify_error
        notify_error(phase, account or "news", str(e))
        print(f"[Scheduler] ERROR: {e}")


def check_pending_jobs():
    """Poll Google Sheets job_queue for pending jobs and execute them."""
    try:
        from sheets import poll_pending_jobs, update_job_status, prune_old_jobs
    except Exception as e:
        print(f"[JobQueue] Failed to import sheets: {e}")
        return

    jobs = poll_pending_jobs()
    if not jobs:
        return

    ran_any = False
    for j in jobs:
        sheet_row = j["sheet_row"]
        jtype     = j["type"]
        params    = j["params"]

        update_job_status(sheet_row, "running")
        ran_any = True

        try:
            if jtype == "phase1":
                from main import run_phase1
                account = params.get("account_type", "news")
                print(f"[JobQueue] Running Phase 1 for {account}")
                run_phase1(account)

            elif jtype == "phase2":
                from main import run_phase2_for_story
                date  = params.get("date")
                index = params.get("story_index", 0)
                print(f"[JobQueue] Running Phase 2 for {date} story {index}")
                run_phase2_for_story(date, index)

            elif jtype == "phase3":
                from main import run_phase3
                account = params.get("account_type", "news")
                trigger = params.get("trigger", "manual_tts")
                slug    = params.get("slug")
                force   = params.get("force", False)
                print(f"[JobQueue] Running Phase 3 for {account} trigger={trigger}")
                run_phase3(account, trigger, slug, force)

            elif jtype == "breaking-scan":
                from discover import scan_for_breaking
                from breaking import run_breaking
                account = params.get("account_type", "news")
                print(f"[JobQueue] Running breaking news scan for {account}")
                found = scan_for_breaking(account)
                if found:
                    print(f"[JobQueue] {len(found)} breaking stories found — processing")
                    run_breaking()
                else:
                    print("[JobQueue] No breaking stories found")

            elif jtype == "breaking-visuals":
                from images import run_image_generation
                from clips  import run_clip_generation
                from sheets import update_breaking_job, _get_sheet
                from config import get_style
                import json
                job_id  = params.get("job_id")
                account = params.get("account_type", "news")
                print(f"[JobQueue] Generating breaking visuals for {job_id}")
                sheet = _get_sheet()
                rows = sheet.get_all_values()
                script_data = None
                for row in reversed(rows):
                    if len(row) >= 5 and f"breaking_{job_id}" == row[3]:
                        data = json.loads(row[4])
                        script_data = data.get("script")
                        break
                if script_data:
                    imgs  = run_image_generation(script_data, get_style(account))
                    clips = run_clip_generation(imgs, account)
                    update_breaking_job(job_id, {"clips": clips, "phase2": "done"})
                    try:
                        from breaking import _load_active, _save_active
                        active = _load_active()
                        for aj in active:
                            if aj.get("job_id") == job_id:
                                aj["visuals_status"] = "done"
                                break
                        _save_active(active)
                    except Exception:
                        pass
                    print(f"[JobQueue] Breaking visuals complete for {job_id}")
                else:
                    print(f"[JobQueue] Could not find script for breaking job {job_id}")

            else:
                print(f"[JobQueue] Unknown job type: {jtype}")
                update_job_status(sheet_row, "error", f"Unknown job type: {jtype}")
                continue

            update_job_status(sheet_row, "complete")

        except Exception as e:
            print(f"[JobQueue] Job failed: {e}")
            update_job_status(sheet_row, "error", str(e))
            try:
                from notify import notify_error
                notify_error(jtype, params.get("account_type", "news"), str(e))
            except Exception:
                pass

    if ran_any:
        try:
            prune_old_jobs(hours=48)
        except Exception:
            pass


# ── Scheduled jobs ─────────────────────────────────────────────────────────

# HOME DAYS (Sun=0, Mon=1, Tue=2) -- UTC times (EST+5)
schedule.every().sunday.at("17:00").do(job, "1", "news")
schedule.every().monday.at("17:00").do(job, "1", "news")
schedule.every().tuesday.at("17:00").do(job, "1", "news")

# TTS fallbacks home days at 2pm EST = 19:00 UTC
schedule.every().sunday.at("19:00").do(job, "3 news --trigger cron_fallback", "")
schedule.every().monday.at("19:00").do(job, "3 news --trigger cron_fallback", "")
schedule.every().tuesday.at("19:00").do(job, "3 news --trigger cron_fallback", "")

# WORK DAYS (Wed=2, Thu=3, Fri=4, Sat=5) -- 6pm EST = 23:00 UTC
schedule.every().wednesday.at("23:00").do(job, "1", "news")
schedule.every().thursday.at("23:00").do(job, "1", "news")
schedule.every().friday.at("23:00").do(job, "1", "news")
schedule.every().saturday.at("23:00").do(job, "1", "news")

# Midnight fallbacks work days
schedule.every().thursday.at("05:00").do(job, "3", "news --trigger midnight_fallback")
schedule.every().friday.at("05:00").do(job, "3", "news --trigger midnight_fallback")
schedule.every().saturday.at("05:00").do(job, "3", "news --trigger midnight_fallback")
schedule.every().sunday.at("05:00").do(job, "3", "news --trigger midnight_fallback")

# Morning fallbacks at 8am EST = 13:00 UTC
schedule.every().thursday.at("13:00").do(job, "3", "news --trigger morning_fallback")
schedule.every().friday.at("13:00").do(job, "3", "news --trigger morning_fallback")
schedule.every().saturday.at("13:00").do(job, "3", "news --trigger morning_fallback")
schedule.every().sunday.at("13:00").do(job, "3", "news --trigger morning_fallback")

# Weekly recap Sunday 8am EST = 13:00 UTC
schedule.every().sunday.at("13:00").do(job, "recap", "")

# Poll Sheets job_queue every 15 seconds for API-enqueued work
schedule.every(15).seconds.do(check_pending_jobs)

print("Scheduler running. All times UTC. Polling Sheets job_queue every 15s.")
while True:
    schedule.run_pending()
    time.sleep(10)
