# breaking.py -- breaking news detection, processing, and decision handling
# Integrates with pipeline-api routes and stories_page.html dashboard

import os, json, datetime
from flask import Flask
from script  import write_script, audit_bias, quality_check
from sheets  import create_breaking_job, update_breaking_job, log_job
from notify  import send_notification
from config  import get_style

app = Flask(__name__)
SERVER_URL = os.getenv("SERVER_URL")  # e.g. https://yourapp.railway.app

BREAKING_ACTIVE_PATH = os.path.join(os.path.dirname(__file__), "breaking_active.json")


# ── Active jobs file helpers ──────────────────────────────────────────────────

def _load_active():
    if not os.path.exists(BREAKING_ACTIVE_PATH):
        return []
    try:
        with open(BREAKING_ACTIVE_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_active(jobs):
    with open(BREAKING_ACTIVE_PATH, "w") as f:
        json.dump(jobs, f, indent=2)


def get_active_breaking():
    """Return active breaking jobs (no decision made yet, less than 2 hours old)."""
    jobs = _load_active()
    now = datetime.datetime.now()
    active = []
    for j in jobs:
        # Skip jobs that already have a decision
        if j.get("decision"):
            continue
        # Skip jobs older than 2 hours (auto-hold)
        try:
            created = datetime.datetime.fromisoformat(j["created_at"])
            if (now - created).total_seconds() > 7200:
                continue
        except (KeyError, ValueError):
            continue
        active.append(j)
    return active


# ── Core breaking handler ─────────────────────────────────────────────────────

def handle_breaking(story, urgency, account_type):
    """Process a breaking story: write script, log job, enqueue visuals, notify."""
    script = write_script(story, account_type)
    if account_type == "news":
        script = audit_bias(script)
    script = quality_check(script)
    job_id = create_breaking_job(story, script, account_type)

    # Enqueue visual generation via pending_jobs.json (same as pipeline-cron pattern)
    from pipeline_api import _enqueue_job
    _enqueue_job("breaking-visuals",
                 job_id=job_id,
                 account_type=account_type)

    # Save to breaking_active.json for dashboard
    active_jobs = _load_active()
    active_jobs.append({
        "job_id":       job_id,
        "title":        story.get("title", "Breaking Story"),
        "summary":      story.get("summary", ""),
        "urgency":      urgency,
        "account_type": account_type,
        "script_preview": script.get("script", "")[:300],
        "created_at":   datetime.datetime.now().isoformat(),
        "decision":     None,
        "visuals_status": "generating",
    })
    _save_active(active_jobs)

    # Pushover: announcement only — decision happens in dashboard
    stories_url = f"{SERVER_URL}/stories"
    send_notification(
        title   = f"BREAKING ({urgency}/10): {story['title'][:50]}",
        message = (
            f"{script.get('script', '')[:200]}...\n\n"
            "Visuals generating now.\n\n"
            f"Open dashboard to approve:\n{stories_url}"
        ),
        priority = "breaking",
    )


def resolve_breaking(job_id, decision):
    """Record a bypass/hold decision for a breaking job.

    decision: "tts" or "hold"
    """
    update_breaking_job(job_id, {"decision": decision})

    # Update local active file
    active_jobs = _load_active()
    for j in active_jobs:
        if j.get("job_id") == job_id:
            j["decision"] = decision
            j["decided_at"] = datetime.datetime.now().isoformat()
            break
    _save_active(active_jobs)

    # If TTS, enqueue Phase 3
    if decision == "tts":
        from pipeline_api import _enqueue_job
        _enqueue_job("phase3",
                     account_type="news",
                     trigger="breaking_tts")


# ── Flask routes (registered on the shared app) ──────────────────────────────

@app.route("/breaking/<job_id>/bypass")
def bypass(job_id):
    resolve_breaking(job_id, "tts")
    return "TTS pipeline triggered. Video will post at next optimal time.", 200


@app.route("/breaking/<job_id>/hold")
def hold(job_id):
    resolve_breaking(job_id, "hold")
    return "Job held. Drop your VO in Drive/pending/ when ready.", 200


# ── Batch processor ──────────────────────────────────────────────────────────

def run_breaking():
    """Process stored breaking candidates from temp/breaking_candidates.json."""
    filepath = os.path.join("temp", "breaking_candidates.json")
    if not os.path.exists(filepath):
        print("[Breaking] No breaking candidates found.")
        return
    with open(filepath, "r") as f:
        candidates = json.load(f)
    for c in candidates:
        handle_breaking(c["story"], c["urgency"], c["account_type"])
    print(f"[Breaking] Processed {len(candidates)} breaking stories.")
