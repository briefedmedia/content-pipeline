import tempfile, os, datetime

# Cross-platform temp directory
# Returns C:\Users\...\AppData\Local\Temp on Windows
# Returns /tmp on Linux (Railway)
TMP = tempfile.gettempdir()

CLAUDE_MODEL_FAST = "claude-sonnet-4-6"   # discovery, selection, trimming
CLAUDE_MODEL_BEST = "claude-opus-4-6"     # script writing, bias audit, quality check

# Change this ONE LINE to switch generators globally
VIDEO_GENERATOR = "pika"   # options: "pika" or "runway"

# Per-account override -- wins over global setting
VIDEO_GENERATOR_OVERRIDE = {
    "history": "runway",   # cinematic quality worth the cost
    "news":    "pika",     # consistency + cost efficiency
}

def get_generator(account_type):
    return VIDEO_GENERATOR_OVERRIDE.get(account_type, VIDEO_GENERATOR)

def get_style(account_type):
    return "history_old" if account_type == "history" else "news"

# Caption mode per platform
CAPTION_MODE = {
    "tiktok":    "native",  # native algorithmically preferred
    "youtube":   "native",  # native + SRT sidecar for search indexing
    "instagram": "baked",   # baked-in -- Instagram auto-captions unreliable
}

# Day-of-week schedule
WORK_DAYS = [2, 3, 4, 5]   # Wed=2 Thu=3 Fri=4 Sat=5
HOME_DAYS = [6, 0, 1]      # Sun=6 Mon=0 Tue=1
def is_work_day(): return datetime.datetime.now().weekday() in WORK_DAYS
def is_home_day(): return datetime.datetime.now().weekday() in HOME_DAYS
def is_sunday():   return datetime.datetime.now().weekday() == 6

# Phase 3 TTS fallback times
PHASE3_FALLBACK = {
    "home_day":          "14:00",  # 2pm if no VO by afternoon
    "work_day_tonight":  "00:00",  # midnight fallback
    "work_day_tomorrow": "08:00",  # 8am final safety net
}

# Optimal posting times
OPTIMAL_POST_TIMES = {
    "tiktok": {
        "sunday":   ["09:00","19:00","21:00"],
        "monday":   ["06:00","10:00","22:00"],
        "tuesday":  ["09:00","19:00","21:00"],
        "wednesday":["09:00","17:00","21:00"],
        "thursday": ["12:00","17:00","21:00"],
        "friday":   ["09:00","12:00","17:00"],
        "saturday": ["11:00","19:00","21:00"],
    },
    "instagram": {
        "sunday":   ["08:00","18:00","20:00"],
        "monday":   ["06:00","12:00","20:00"],
        "tuesday":  ["08:00","17:00","20:00"],
        "wednesday":["11:00","17:00","20:00"],
        "thursday": ["11:00","17:00","20:00"],
        "friday":   ["09:00","12:00","17:00"],
        "saturday": ["09:00","18:00","20:00"],
    },
    "youtube": {"default": ["15:00","18:00","20:00"]},
}

def get_next_optimal_time(platform):
    now = datetime.datetime.now()
    day = now.strftime("%A").lower()
    times = OPTIMAL_POST_TIMES[platform].get(
        day, OPTIMAL_POST_TIMES[platform].get("default", ["18:00"]))
    for t in times:
        slot = datetime.datetime.strptime(f"{now.date()} {t}", "%Y-%m-%d %H:%M")
        if slot > now + datetime.timedelta(minutes=30):
            return slot
    tomorrow = (now + datetime.timedelta(days=1)).strftime("%A").lower()
    first = OPTIMAL_POST_TIMES[platform].get(tomorrow, ["09:00"])[0]
    return datetime.datetime.strptime(
        f"{(now+datetime.timedelta(days=1)).date()} {first}", "%Y-%m-%d %H:%M")        

# Auto-publish toggle
# Set to False to disable all uploading -- pipeline still runs and saves to Drive
# Set per-platform to control individually
AUTO_PUBLISH = {
    "tiktok":    False,
    "youtube":   False,
    "instagram": False,
}
# Minimum explainability score to qualify for video production
# Stories scoring below this are filtered out and replaced with next candidate
# Scale: 1-10. 6 = has meaningful historical context. Raise to 7 as quality bar increases.
MIN_EXPLAINABILITY_SCORE = 6

TTS_PROVIDER  = "google"   # options: "google", "edge"
EDGE_TTS_VOICE = {
    "news":    "en-US-GuyNeural",
    "history": "en-US-GuyNeural",
}
GOOGLE_TTS_VOICE = {
    "news":    "en-US-Neural2-D",   # authoritative male
    "history": "en-US-Neural2-J",   # warmer male
}