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
# PRIORITY LEVELS USED IN THIS PIPELINE:
#   "breaking"   -- highest: bypasses DND, siren sound, retries every 30s
#                   used for: breaking news alerts
#   "publishing" -- high: bypasses DND, loud sound, no retry
#                   used for: publish confirmations, publish failures
#   "normal"     -- standard: respects quiet hours, default sound
#                   used for: all routine pipeline progress updates

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

    priority="normal"     -- routine pipeline updates
    priority="publishing" -- publish confirmations and failures (high, no retry)
    priority="breaking"   -- breaking news alerts (highest, retries until ack)
    """
    if not PUSHOVER_TOKEN or not PUSHOVER_USER_KEY:
        print(f"Pushover not configured -- notification skipped: {title}")
        print("Add PUSHOVER_TOKEN and PUSHOVER_USER_KEY to your .env file")
        return

    # Map priority names to Pushover priority integers
    # -1 = quiet, 0 = normal, 1 = high (bypasses DND), 2 = emergency (retries)
    priority_map = {
        "normal":     0,
        "publishing": 1,
        "breaking":   2,
    }
    pushover_priority = priority_map.get(priority, 0)

    # Sound selection
    sound_map = {
        "normal":     "pushover",
        "publishing": "cashregister",
        "breaking":   "siren",
    }
    sound = sound_map.get(priority, "pushover")

    payload = {
        "token":    PUSHOVER_TOKEN,
        "user":     PUSHOVER_USER_KEY,
        "title":    title,
        "message":  message,
        "priority": pushover_priority,
        "sound":    sound,
    }

    # Emergency priority (breaking news) requires retry + expiry
    if pushover_priority == 2:
        payload["retry"]  = 30    # retry every 30 seconds
        payload["expire"] = 7200  # stop after 2 hours (matches pipeline timeout)

    try:
        response = requests.post(PUSHOVER_URL, data=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        if result.get("status") == 1:
            print(f"  Notification sent [{priority}]: {title}")
        else:
            print(f"  Pushover error: {result.get('errors', 'unknown error')}")
    except requests.exceptions.Timeout:
        print(f"  Pushover timed out -- notification may not have delivered: {title}")
    except requests.exceptions.RequestException as e:
        print(f"  Pushover request failed: {e} -- notification skipped: {title}")


# ── Phase 1 -- Discovery ───────────────────────────────────────────────────────

def notify_stories_ready(candidates, date, server_url, auto_select_minutes=120):
    """
    Send one Pushover notification per story so each is tappable and clean.
    First notification also includes the auto-select warning.
    """
    for i, s in enumerate(candidates):
        score = 0
        hook  = ""
        if s.get("historical_context"):
            score = s["historical_context"].get("explainability_score", 0)
            hook  = s["historical_context"].get("suggested_hook", "")[:100]

        approve_url = f"{server_url}/approve/{date}/{i}"

        # First story gets the auto-select warning
        footer = f"\nAuto-selects story #1 in {auto_select_minutes} mins if no response." if i == 0 else ""

        send_notification(
            title   = f"Story {i+1} of {len(candidates)} [{score}/10]: {s['title'][:50]}",
            message = f"{hook}\n\nTap to approve:\n{approve_url}{footer}",
            priority = "normal"
        )


def notify_story_approved(title, index, account_type):
    """Confirmation when a story approval tap is received."""
    send_notification(
        title   = f"Story approved -- Phase 2 starting",
        message = (
            f"Story #{index + 1}: {title}\n"
            f"Account: {account_type}\n\n"
            "Script writing, image generation, and clip generation are now running.\n"
            "You'll be notified when the silent preview is ready."
        ),
        priority = "normal"
    )


def notify_auto_approved(title, account_type):
    """Notification when auto-approval fires after timeout with no response."""
    send_notification(
        title   = f"Auto-approved -- no response in 2 hours",
        message = (
            f"Story: {title}\n"
            f"Account: {account_type}\n\n"
            "Story #1 was auto-selected because no approval tap was received.\n"
            "Phase 2 is now running."
        ),
        priority = "normal"
    )


# ── Phase 2 -- Script, Images, Clips ──────────────────────────────────────────

def notify_script_ready(title, script_preview, account_type, passed_checks):
    """Script written and checked -- Phase 2 continuing to images."""
    check_status = "Passed all checks" if passed_checks else "WARNING: Review flagged items in Drive/02_scripts/"
    send_notification(
        title   = f"Script ready ({account_type}): {title}",
        message = (
            f"{script_preview[:300]}...\n\n"
            f"Quality: {check_status}\n\n"
            "Images and clips generating now.\n"
            "Will notify when silent preview is ready."
        ),
        priority = "normal"
    )


def notify_preview_ready(title, account_type, preview_drive_path):
    """Silent preview assembled -- ready for VO recording."""
    send_notification(
        title   = f"Preview ready -- record your VO now",
        message = (
            f"Story: {title}\n"
            f"Account: {account_type}\n\n"
            f"Watch the silent preview in Drive:\n{preview_drive_path}\n\n"
            "When ready, record your voiceover and drop it in:\n"
            "Drive/05_audio/pending/\n\n"
            "File watcher will detect it and start Phase 3 automatically."
        ),
        priority = "normal"
    )


def notify_images_complete(title, scene_count, account_type):
    """All images generated successfully."""
    send_notification(
        title   = f"Images complete ({account_type})",
        message = (
            f"Story: {title}\n"
            f"{scene_count} scenes generated and uploaded to Drive/03_images/\n\n"
            "Clip generation running now."
        ),
        priority = "normal"
    )


def notify_clips_complete(title, clip_count, generator, account_type):
    """All video clips generated successfully."""
    send_notification(
        title   = f"Clips complete ({account_type})",
        message = (
            f"Story: {title}\n"
            f"{clip_count} clips generated via {generator}\n"
            "Uploaded to Drive/04_clips/\n\n"
            "Assembling silent preview now."
        ),
        priority = "normal"
    )


# ── Phase 3 -- Audio, Assembly, Publish ───────────────────────────────────────

def notify_recording_detected(title, account_type):
    """Human VO recording detected in pending folder -- Phase 3 starting."""
    send_notification(
        title   = f"Recording detected -- Phase 3 starting",
        message = (
            f"Story: {title}\n"
            f"Account: {account_type}\n\n"
            "Your voice recording was found in Drive/05_audio/pending/\n"
            "Transcribing, assembling, and captioning now.\n"
            "Final video ready in ~15 minutes."
        ),
        priority = "normal"
    )


def notify_tts_fallback(title, account_type, trigger):
    """TTS was used because no human VO was found by deadline."""
    trigger_labels = {
        "cron_fallback":    "2pm same-day deadline",
        "midnight_fallback": "midnight deadline",
        "morning_fallback": "8am final deadline",
    }
    trigger_label = trigger_labels.get(trigger, trigger)
    send_notification(
        title   = f"TTS fallback used ({account_type})",
        message = (
            f"Story: {title}\n"
            f"Trigger: {trigger_label}\n\n"
            "No voice recording was found in Drive/05_audio/pending/ by the deadline.\n"
            "Google TTS (AI voice) has been used instead.\n"
            "Final video assembling now."
        ),
        priority = "normal"
    )


def notify_video_complete(title, duration, account_type, has_shorts):
    """Final video assembled and uploaded to Drive -- ready for review."""
    shorts_note = "\nYouTube Shorts cut also generated." if has_shorts else ""
    send_notification(
        title   = f"Video complete ({account_type}): {title}",
        message = (
            f"Duration: {duration:.0f}s\n"
            f"Account: {account_type}{shorts_note}\n\n"
            "Files saved to Drive/07_final/\n"
            "Clean MP4 + captioned MP4 both ready.\n\n"
            "Auto-publish is disabled -- post manually when ready."
        ),
        priority = "normal"
    )


def notify_shorts_ready(title, duration, account_type):
    """YouTube Shorts cut assembled separately."""
    send_notification(
        title   = f"Shorts cut ready ({account_type})",
        message = (
            f"Story: {title}\n"
            f"Duration: {duration:.0f}s\n\n"
            "Saved to Drive/07_final/ alongside clean and captioned versions.\n"
            "Ready for YouTube Shorts upload."
        ),
        priority = "normal"
    )


def notify_ambient_failed(title, account_type):
    """Freesound search returned nothing for all scenes."""
    send_notification(
        title   = f"Ambient audio unavailable ({account_type})",
        message = (
            f"Story: {title}\n\n"
            "Freesound returned no CC0 results for all scenes.\n"
            "Video assembled without ambient audio.\n\n"
            "If this keeps happening, check FREESOUND_API_KEY in your env vars."
        ),
        priority = "normal"
    )


# ── Publishing ────────────────────────────────────────────────────────────────

def notify_published(title, platforms, account_type):
    """Video successfully published to one or more platforms."""
    platform_str = ", ".join(platforms)
    send_notification(
        title   = f"Published: {title}",
        message = (
            f"Account: {account_type}\n"
            f"Posted to: {platform_str}\n\n"
            "Check your accounts to confirm everything looks correct.\n"
            "Saved to Drive/08_published/"
        ),
        priority = "publishing"
    )


def notify_publish_failed(title, platform, error_summary, account_type):
    """Publishing failed on a specific platform."""
    send_notification(
        title   = f"PUBLISH FAILED: {platform}",
        message = (
            f"Story: {title}\n"
            f"Account: {account_type}\n"
            f"Platform: {platform}\n\n"
            f"Error: {error_summary[:300]}\n\n"
            "Video is in Drive/07_final/ -- post manually."
        ),
        priority = "publishing"
    )


def notify_shorts_published(title, account_type):
    """YouTube Shorts successfully published."""
    send_notification(
        title   = f"Shorts published: {title}",
        message = (
            f"Account: {account_type}\n\n"
            "YouTube Shorts cut is now live.\n"
            "Check your YouTube channel to confirm."
        ),
        priority = "publishing"
    )


# ── Breaking News ─────────────────────────────────────────────────────────────

def notify_breaking_news(title, urgency_score, script_preview,
                         bypass_url, hold_url):
    """
    Breaking news detected -- highest priority, retries until acknowledged.
    Visuals are already generating regardless of decision.
    """
    send_notification(
        title   = f"BREAKING ({urgency_score}/10): {title}",
        message = (
            f"{script_preview[:300]}...\n\n"
            "Visuals generating NOW regardless of your decision.\n\n"
            f"TAP -- USE AI VOICE (faster publish):\n{bypass_url}\n\n"
            f"TAP -- HOLD FOR YOUR VO:\n{hold_url}\n\n"
            "No response in 2 hours = HOLD default."
        ),
        priority = "breaking"
    )


def notify_breaking_bypassed(title, urgency_score):
    """Confirmation that bypass was tapped -- TTS path selected."""
    send_notification(
        title   = f"Breaking: AI voice selected",
        message = (
            f"Story: {title}\n"
            f"Urgency: {urgency_score}/10\n\n"
            "TTS path confirmed. Final video assembling now.\n"
            "Will notify when complete."
        ),
        priority = "breaking"
    )


def notify_breaking_held(title, urgency_score):
    """Confirmation that hold was tapped -- waiting for human VO."""
    send_notification(
        title   = f"Breaking: Holding for your VO",
        message = (
            f"Story: {title}\n"
            f"Urgency: {urgency_score}/10\n\n"
            "Waiting for your voice recording in Drive/05_audio/pending/\n"
            "Drop it in when ready -- watcher will detect it automatically."
        ),
        priority = "breaking"
    )


def notify_breaking_auto_held(title, urgency_score):
    """2-hour timeout expired with no response -- defaulted to HOLD."""
    send_notification(
        title   = f"Breaking: Auto-held after 2hr timeout",
        message = (
            f"Story: {title}\n"
            f"Urgency: {urgency_score}/10\n\n"
            "No bypass or hold tap received within 2 hours.\n"
            "Defaulted to HOLD -- drop your VO in Drive/05_audio/pending/ when ready."
        ),
        priority = "breaking"
    )


# ── Errors ────────────────────────────────────────────────────────────────────

def notify_error(phase, account_type, error_summary):
    """Pipeline error requiring attention."""
    send_notification(
        title   = f"Pipeline error -- Phase {phase} ({account_type})",
        message = (
            f"The pipeline failed during Phase {phase}.\n\n"
            f"Error: {error_summary[:300]}\n\n"
            "Check Google Sheets log for full details.\n"
            "Pipeline has stopped -- manual restart required."
        ),
        priority = "normal"
    )


def notify_build_warning(title, account_type, warning):
    """Non-fatal warning that needs awareness but didn't stop the pipeline."""
    send_notification(
        title   = f"Pipeline warning ({account_type})",
        message = (
            f"Story: {title}\n\n"
            f"Warning: {warning[:300]}\n\n"
            "Pipeline continued but review this before publishing."
        ),
        priority = "normal"
    )