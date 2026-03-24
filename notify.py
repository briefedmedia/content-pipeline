# notify.py -- all pipeline notifications via Pushover
# $5 one-time purchase at pushover.net
# iOS and Android app, works instantly after setup
#
# SETUP:
# 1. Buy Pushover at pushover.net ($5 one-time, covers all your devices)
# 2. Install the Pushover app on your phone
# 3. In the Pushover dashboard, create an Application called "Briefed Pipeline"
# 4. Copy your User Key and the Application API Token
# 5. Add both to your .env file:
#       PUSHOVER_TOKEN=your-application-token
#       PUSHOVER_USER_KEY=your-user-key
#
# PRIORITY LEVELS:
#   "normal"   -- delivers with standard sound, respects Do Not Disturb
#   "breaking" -- bypasses Do Not Disturb, plays siren sound, retries every
#                 30 seconds until you acknowledge it on your phone

import requests
import os
from dotenv import load_dotenv

load_dotenv()

PUSHOVER_TOKEN    = os.getenv("PUSHOVER_TOKEN")
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_URL      = "https://api.pushover.net/1/messages.json"


def send_notification(title, message, priority="normal"):
    """
    Send a push notification via Pushover.

    priority="normal"   -- routine pipeline updates (script ready, preview
                           ready, video complete, recording detected)
    priority="breaking" -- breaking news alerts requiring your decision
                           within 2 hours (bypass TTS or hold for your VO)
    """
    if not PUSHOVER_TOKEN or not PUSHOVER_USER_KEY:
        print(f"Pushover not configured -- notification skipped: {title}")
        print("Add PUSHOVER_TOKEN and PUSHOVER_USER_KEY to your .env file")
        return

    is_breaking = priority == "breaking"

    payload = {
        "token":   PUSHOVER_TOKEN,
        "user":    PUSHOVER_USER_KEY,
        "title":   title,
        "message": message,

        # Priority 1 = high priority: bypasses DND, plays siren, retries
        # Priority 0 = normal: standard delivery, respects quiet hours
        "priority": 1 if is_breaking else 0,

        # Siren for breaking news so you always hear it
        # Default Pushover sound for everything else
        "sound": "siren" if is_breaking else "pushover",
    }

    # Breaking news requires retry + expiry settings for priority 1
    if is_breaking:
        payload["retry"]  = 30    # retry every 30 seconds if not acknowledged
        payload["expire"] = 7200  # stop retrying after 2 hours (matches pipeline timeout)

    try:
        response = requests.post(PUSHOVER_URL, data=payload, timeout=10)
        response.raise_for_status()
        result = response.json()

        if result.get("status") == 1:
            print(f"Notification sent: {title}")
        else:
            print(f"Pushover error: {result.get('errors', 'unknown error')}")

    except requests.exceptions.Timeout:
        print(f"Pushover timed out -- notification may not have delivered: {title}")
    except requests.exceptions.RequestException as e:
        print(f"Pushover request failed: {e} -- notification skipped: {title}")


# ── Convenience wrappers for common pipeline events ───────────────────────────
# These are optional -- you can call send_notification() directly anywhere
# in the pipeline, but these make the call sites in main.py cleaner.

def notify_script_ready(title, script_preview, account_type):
    send_notification(
        title   = f"Script ready ({account_type}): {title}",
        message = (
            f"{script_preview[:300]}...\n\n"
            "Visuals generating now (~2 hrs).\n"
            "Will notify when preview is ready to watch."
        ),
        priority = "normal"
    )


def notify_preview_ready(title, account_type):
    send_notification(
        title   = f"Preview ready ({account_type}): {title}",
        message = (
            "Your rough cut is in Drive/previews/\n"
            "Watch it, record your VO, then drop the file in:\n"
            "Drive/05_audio/pending/\n\n"
            "File watcher will start Phase 3 automatically."
        ),
        priority = "normal"
    )


def notify_recording_detected(title, account_type):
    send_notification(
        title   = f"Recording detected -- building final video",
        message = (
            f"Account: {account_type}\n"
            f"Story: {title}\n\n"
            "Final video will be ready in ~15 minutes."
        ),
        priority = "normal"
    )


def notify_video_complete(title, duration, account_type):
    send_notification(
        title   = f"Video complete ({account_type}): {title}",
        message = (
            f"Duration: {duration:.0f}s\n"
            "Saved to Drive/07_final/\n\n"
            "Auto-publish is disabled -- post manually when ready."
        ),
        priority = "normal"
    )


def notify_breaking_news(title, urgency_score, script_preview,
                         bypass_url, hold_url):
    send_notification(
        title   = f"BREAKING ({urgency_score}/10): {title}",
        message = (
            f"{script_preview[:300]}...\n\n"
            "Visuals generating now regardless of your decision.\n\n"
            f"TAP TO USE TTS (post faster):\n{bypass_url}\n\n"
            f"TAP TO HOLD (record your VO):\n{hold_url}\n\n"
            "No response in 2 hours = HOLD"
        ),
        priority = "breaking"
    )


def notify_error(phase, account_type, error_summary):
    send_notification(
        title   = f"Pipeline error -- Phase {phase} ({account_type})",
        message = (
            f"The pipeline failed during Phase {phase}.\n\n"
            f"Error: {error_summary[:300]}\n\n"
            "Check Google Sheets log for full details."
        ),
        priority = "normal"
    )