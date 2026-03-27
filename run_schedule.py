# run_schedule.py -- internal scheduler for Railway pipeline-cron service
import schedule, time, os, json

PENDING_JOBS_PATH = os.path.join(os.path.dirname(__file__), "pending_jobs.json")

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
    """Poll pending_jobs.json and execute any pending Phase 1/2/3 jobs."""
    if not os.path.exists(PENDING_JOBS_PATH):
        return
    try:
        with open(PENDING_JOBS_PATH) as f:
            jobs = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    changed = False
    for j in jobs:
        if j.get("status") != "pending":
            continue

        j["status"] = "running"
        _save_jobs(jobs)
        changed = True

        jtype = j.get("type", "")
        try:
            if jtype == "phase1":
                from main import run_phase1
                account = j.get("account_type", "news")
                print(f"[JobQueue] Running Phase 1 for {account}")
                run_phase1(account)
                j["status"] = "complete"

            elif jtype == "phase2":
                from main import run_phase2_for_story
                date  = j.get("date")
                index = j.get("story_index", 0)
                print(f"[JobQueue] Running Phase 2 for {date} story {index}")
                run_phase2_for_story(date, index)
                j["status"] = "complete"

            elif jtype == "phase3":
                from main import run_phase3
                account = j.get("account_type", "news")
                trigger = j.get("trigger", "manual_tts")
                slug    = j.get("slug")
                force   = j.get("force", False)
                print(f"[JobQueue] Running Phase 3 for {account} trigger={trigger}")
                run_phase3(account, trigger, slug, force)
                j["status"] = "complete"

            elif jtype == "breaking-scan":
                from discover import scan_for_breaking
                from breaking import run_breaking
                account = j.get("account_type", "news")
                print(f"[JobQueue] Running breaking news scan for {account}")
                found = scan_for_breaking(account)
                if found:
                    print(f"[JobQueue] {len(found)} breaking stories found — processing")
                    run_breaking()
                else:
                    print("[JobQueue] No breaking stories found")
                j["status"] = "complete"

            else:
                print(f"[JobQueue] Unknown job type: {jtype}")
                j["status"] = "error"

        except Exception as e:
            print(f"[JobQueue] Job failed: {e}")
            j["status"] = "error"
            j["error"]  = str(e)
            try:
                from notify import notify_error
                notify_error(jtype, j.get("account_type", "news"), str(e))
            except Exception:
                pass

        _save_jobs(jobs)

    # Prune completed/error jobs older than 24 hours
    if changed:
        _prune_old_jobs()


def _save_jobs(jobs):
    with open(PENDING_JOBS_PATH, "w") as f:
        json.dump(jobs, f, indent=2)


def _prune_old_jobs():
    """Remove completed/error jobs older than 24 hours to prevent file growth."""
    import datetime
    try:
        with open(PENDING_JOBS_PATH) as f:
            jobs = json.load(f)
        cutoff = (datetime.datetime.now() - datetime.timedelta(hours=24)).isoformat()
        kept = [j for j in jobs
                if j.get("status") == "pending"
                or j.get("status") == "running"
                or j.get("requested_at", "") > cutoff]
        _save_jobs(kept)
    except Exception:
        pass

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

# Poll pending_jobs.json every 60 seconds for API-enqueued work
schedule.every(15).seconds.do(check_pending_jobs)

print("Scheduler running. All times UTC. Polling pending_jobs.json every 15s.")
while True:
    schedule.run_pending()
    time.sleep(10)
