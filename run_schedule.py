# run_schedule.py -- internal scheduler for Railway pipeline-cron service
import schedule, time, os

def job(phase, account):
    cmd = f"python main.py {phase} {account}".strip()
    print(f"[Scheduler] Running: {cmd}")
    result = os.system(cmd)
    if result != 0:
        print(f"[Scheduler] WARNING: {cmd} exited with code {result} -- not retrying")

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

print("Scheduler running. All times UTC.")
while True:
    schedule.run_pending()
    time.sleep(60)
