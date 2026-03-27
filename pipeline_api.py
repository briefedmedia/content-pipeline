# pipeline_api.py -- Railway "pipeline-api" service entry point
# Start command: python pipeline_api.py
# Includes breaking news bypass/hold routes (from breaking.py) + utility endpoints
#
# Railway deployment:
#   Service: pipeline-api
#   Start command: python pipeline_api.py
#   Port: 8080 (set PORT env var in Railway or use default below)

import json
import datetime
import os
from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

from breaking import app  # imports Flask app with /breaking/<id>/bypass and /breaking/<id>/hold
from config import TMP
from approvals import load_approvals, save_approvals
import drive

PORT = int(os.getenv("PORT", 8080))

@app.route("/")
def dashboard():
    return open("dashboard.html").read(), 200, {"Content-Type": "text/html"}


@app.route("/costs")
def costs_page():
    if os.path.exists("costs_page.html"):
        return open("costs_page.html").read(), 200, {"Content-Type": "text/html"}
    return "<h2>costs_page.html not found</h2>", 404


@app.route("/stories")
def stories_page():
    import os as _os
    if _os.path.exists("stories_page.html"):
        return open("stories_page.html").read(), 200, {"Content-Type": "text/html"}
    return "<h2>stories_page.html not found</h2>", 404


@app.route("/candidates/today")
def candidates_today():
    today = datetime.date.today().isoformat()
    path  = os.path.join(TMP, today, f"candidates_{today}.json")
    if not os.path.exists(path):
        return jsonify([])
    with open(path) as f:
        data = json.load(f)
    candidates = data.get("candidates", [])
    out = []
    for c in candidates:
        hc           = c.get("historical_context", {})
        score        = hc.get("explainability_score", c.get("score", 0))
        hook         = hc.get("suggested_hook", "")
        significance = hc.get("significance", c.get("significance", ""))
        sources      = hc.get("wikipedia_articles_used", [])
        if isinstance(sources, str):
            sources = [s.strip() for s in sources.split(",") if s.strip()]
        out.append({
            "title":               c.get("title", ""),
            "score":               score,
            "hook":                hook,
            "significance":        significance,
            "wikipedia_sources":   sources,
            "estimated_cost_low":  0.45,
            "estimated_cost_high": 0.65,
        })
    return jsonify(out)


@app.route("/pipeline/history")
def pipeline_history():
    try:
        from sheets import _get_sheet
        import datetime
        sheet = _get_sheet()
        rows  = sheet.get_all_values()
        today = datetime.date.today()
        days  = {}
        for row in rows:
            if len(row) < 5: continue
            date = row[0] if len(row[0]) == 10 else row[1][:10]
            try:
                d = datetime.date.fromisoformat(date)
                if (today - d).days > 7: continue
            except:
                continue
            if date not in days:
                days[date] = {"date": date, "phase1_status": None,
                              "phase2_status": None, "phase3_status": None,
                              "title": "", "stories": []}
            phase_str = row[3] if len(row) > 3 else ""
            status    = row[4] if len(row) > 4 else ""
            if "phase1" in phase_str or "Phase 1" in phase_str:
                days[date]["phase1_status"] = status.lower()
            elif "phase2" in phase_str or "Phase 2" in phase_str:
                days[date]["phase2_status"] = status.lower()
            elif "phase3" in phase_str or "Phase 3" in phase_str:
                days[date]["phase3_status"] = status.lower()
        return jsonify(sorted(days.values(), key=lambda x: x["date"], reverse=True))
    except Exception as e:
        return jsonify([])


# --- Health check ---
@app.route("/status")
def status():
    return jsonify({"pipeline": "running"})


@app.route("/pipeline/costs")
def pipeline_costs():
    """Cost summary for the cost dashboard page."""
    try:
        from sheets import get_cost_summary
        from costs  import get_fixed_costs, MONTHLY_BUDGET
        n_days  = int(request.args.get("days", 30))
        summary = get_cost_summary(n_days)
        fixed   = get_fixed_costs()
        return jsonify({
            "ok":           True,
            "period_days":  n_days,
            "variable":     summary,
            "fixed":        fixed,
            "budget":       MONTHLY_BUDGET,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/pipeline/costs/prices")
def pipeline_cost_prices():
    """Live FAL pricing + confirmed static rates."""
    try:
        from costs import (
            fetch_fal_pricing,
            CLAUDE_OPUS_INPUT_PER_MTK, CLAUDE_OPUS_OUTPUT_PER_MTK,
            CLAUDE_SONNET_INPUT_PER_MTK, CLAUDE_SONNET_OUTPUT_PER_MTK,
            DALLE3_HD_PER_IMAGE, DALLE3_STD_PER_IMAGE,
            GOOGLE_TTS_NEURAL2_PER_MCHAR, GOOGLE_TTS_FREE_MONTHLY_CHARS,
        )
        fal_prices = fetch_fal_pricing()
        return jsonify({
            "ok": True,
            "claude": {
                "opus_input_per_mtk":    CLAUDE_OPUS_INPUT_PER_MTK,
                "opus_output_per_mtk":   CLAUDE_OPUS_OUTPUT_PER_MTK,
                "sonnet_input_per_mtk":  CLAUDE_SONNET_INPUT_PER_MTK,
                "sonnet_output_per_mtk": CLAUDE_SONNET_OUTPUT_PER_MTK,
            },
            "dalle3": {
                "hd_per_image":  DALLE3_HD_PER_IMAGE,
                "std_per_image": DALLE3_STD_PER_IMAGE,
            },
            "google_tts": {
                "neural2_per_mchar":   GOOGLE_TTS_NEURAL2_PER_MCHAR,
                "free_monthly_chars":  GOOGLE_TTS_FREE_MONTHLY_CHARS,
            },
            "fal": fal_prices,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# --- List pending audio recordings ---
@app.route("/pending")
def pending_files():
    try:
        files = drive.list_pending_recordings()
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- List final videos ---
@app.route("/final")
def final_files():
    try:
        files = drive.list_files("final")
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/approve/<date>/<int:story_index>")
def approve_story(date, story_index):
    approvals = load_approvals()
    if date not in approvals:
        approvals[date] = {"approved": [], "timestamp": datetime.datetime.now().isoformat()}
    if story_index not in approvals[date]["approved"]:
        approvals[date]["approved"].append(story_index)
    save_approvals(approvals)
    try:
        import threading
        from main import run_phase2_for_story
        t = threading.Thread(
            target=run_phase2_for_story,
            args=(date, story_index),
            daemon=True
        )
        t.start()
        return f"""
        <html><body style="font-family:sans-serif;max-width:500px;margin:60px auto;text-align:center;">
        <h2>&#10003; Story {story_index + 1} approved</h2>
        <p>Script and visuals are generating now on Railway.</p>
        <p style="color:#888;font-size:14px;">You'll receive a Pushover notification when the silent preview is ready.<br>
        This usually takes 20–40 minutes.</p>
        </body></html>
        """, 202
    except Exception as e:
        return f"Approval recorded but Phase 2 failed to start: {e}", 500


@app.route("/approve/<date>/status")
def approval_status(date):
    approvals = load_approvals()
    day = approvals.get(date, {})
    return jsonify({
        "approved":          day.get("approved", []),
        "declined":          day.get("declined", []),
        "auto_cancelled":    day.get("auto_cancelled", False),
        "auto_cancelled_at": day.get("auto_cancelled_at", None),
        "timestamp":         day.get("timestamp", None),
    })


@app.route("/approve/<date>/auto")
def auto_approve(date):
    approvals = load_approvals()
    day_data  = approvals.get(date, {"approved": []})
    if day_data.get("auto_cancelled"):
        return "Auto-select was cancelled via dashboard -- skipping.", 200
    if not day_data.get("approved"):
        approvals[date] = {
            "approved":  [0],
            "timestamp": datetime.datetime.now().isoformat(),
            "auto":      True,
        }
        save_approvals(approvals)
        try:
            import threading
            from main import run_phase2_for_story
            t = threading.Thread(target=run_phase2_for_story, args=(date, 0), daemon=True)
            t.start()
            return "Auto-approved story 1. Script and visuals generating.", 200
        except Exception as e:
            return f"Auto-approve triggered but Phase 2 failed: {e}", 500
    return f"Stories already approved: {day_data['approved']}", 200


@app.route("/approve/<date>/cancel-auto", methods=["GET", "POST"])
def cancel_auto_approve(date):
    approvals = load_approvals()
    day = approvals.get(date, {})

    # Expiry guard: if phase1 timestamp exists and > 2 hours ago, reject
    ts = day.get("timestamp")
    if ts:
        try:
            phase1_time = datetime.datetime.fromisoformat(ts)
            if (datetime.datetime.now() - phase1_time).total_seconds() > 7200:
                return jsonify({
                    "error":   "window_expired",
                    "message": "The auto-select window has already closed. Approve a story manually.",
                }), 400
        except Exception:
            pass

    # Ensure the day record exists
    if date not in approvals:
        approvals[date] = {"approved": [], "timestamp": datetime.datetime.now().isoformat()}

    currently_cancelled = approvals[date].get("auto_cancelled", False)

    if not currently_cancelled:
        # Cancel auto-select
        approvals[date]["auto_cancelled"]    = True
        approvals[date]["auto_cancelled_at"] = datetime.datetime.now().isoformat()
        save_approvals(approvals)
        return jsonify({
            "status":         "cancelled",
            "auto_cancelled": True,
            "message":        f"Auto-select disabled for {date}",
        })
    else:
        # Re-enable auto-select
        approvals[date]["auto_cancelled"]    = False
        approvals[date]["auto_cancelled_at"] = None
        save_approvals(approvals)
        return jsonify({
            "status":         "enabled",
            "auto_cancelled": False,
            "message":        f"Auto-select re-enabled for {date}",
        })


@app.route("/approve/<date>/decline/<int:story_index>", methods=["POST"])
def decline_story(date, story_index):
    approvals = load_approvals()
    if date not in approvals:
        approvals[date] = {"approved": [], "declined": [],
                           "timestamp": datetime.datetime.now().isoformat()}
    if "declined" not in approvals[date]:
        approvals[date]["declined"] = []
    if story_index not in approvals[date]["declined"]:
        approvals[date]["declined"].append(story_index)
    save_approvals(approvals)

    # Archive declined story to Drive (non-blocking)
    try:
        today = datetime.date.today().isoformat()
        path  = os.path.join(TMP, today, f"candidates_{today}.json")
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            candidates = data.get("candidates", [])
            if story_index < len(candidates):
                drive.archive_declined_story(date, story_index, candidates[story_index])
    except Exception as e:
        print(f"  Archive declined failed (non-fatal): {e}")

    return jsonify({"status": "declined", "story_index": story_index, "date": date})


@app.route("/approve/<date>/status-detail")
def approval_status_detail(date):
    approvals = load_approvals()
    day = approvals.get(date, {})
    return jsonify({
        "approved":          day.get("approved", []),
        "auto_cancelled":    day.get("auto_cancelled", False),
        "auto_cancelled_at": day.get("auto_cancelled_at", None),
        "timestamp":         day.get("timestamp", None),
    })


@app.route("/approve/force-assemble", methods=["GET", "POST"])
def force_assemble():
    import threading
    from main import run_phase3
    account = request.args.get("account", "news")
    slug    = request.args.get("slug", None)
    t = threading.Thread(
        target=run_phase3,
        args=(account, "manual_force", slug, True),
        daemon=True
    )
    t.start()
    return """
    <html><body style="font-family:-apple-system,sans-serif;max-width:500px;
    margin:60px auto;text-align:center;background:#000;color:#fff;padding:40px;">
    <h2 style="color:#30D158;">&#10003; Force assembling</h2>
    <p style="color:rgba(255,255,255,0.6);">Assembling with current VO timing.<br>
    You'll get a Pushover notification when the video is ready.</p>
    </body></html>
    """, 202


@app.route("/run/phase1", methods=["POST"])
def run_phase1_route():
    import threading, datetime
    from main import run_phase1
    account = request.args.get("account", "news")
    rerun   = request.args.get("rerun", "false").lower() == "true"
    if rerun:
        today = datetime.date.today().isoformat()
        approvals = load_approvals()
        approvals.pop(today, None)
        save_approvals(approvals)
    t = threading.Thread(target=run_phase1, args=(account,), daemon=True)
    t.start()
    return jsonify({"status": "started", "phase": "1", "account": account, "rerun": rerun}), 202


@app.route("/run/phase3", methods=["POST"])
def run_phase3_route():
    import threading
    from main import run_phase3
    account = request.args.get("account", "news")
    trigger = request.args.get("trigger", "manual_tts")
    slug    = request.args.get("slug", None)
    t = threading.Thread(target=run_phase3, args=(account, trigger, slug), daemon=True)
    t.start()
    return jsonify({"status": "started", "phase": "3", "account": account, "trigger": trigger}), 202


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
