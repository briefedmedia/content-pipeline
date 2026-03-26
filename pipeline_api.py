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
from flask import Flask, jsonify
from dotenv import load_dotenv

load_dotenv()

from breaking import app  # imports Flask app with /breaking/<id>/bypass and /breaking/<id>/hold
from config import TMP
import drive

PORT = int(os.getenv("PORT", 8080))

# approvals.json lives in the temp root (not story-specific)
APPROVALS_FILE = os.path.join(TMP, "approvals.json")


def load_approvals():
    if os.path.exists(APPROVALS_FILE):
        with open(APPROVALS_FILE) as f:
            return json.load(f)
    return {}


def save_approvals(data):
    with open(APPROVALS_FILE, "w") as f:
        json.dump(data, f, indent=2)

@app.route("/")
def dashboard():
    return open("dashboard.html").read(), 200, {"Content-Type": "text/html"}


@app.route("/candidates/today")
def candidates_today():
    import datetime
    today = datetime.date.today().isoformat()
    path  = os.path.join(TMP, today, f"candidates_{today}.json")
    if not os.path.exists(path):
        return jsonify([])
    with open(path) as f:
        data = json.load(f)
    candidates = data.get("candidates", [])
    out = []
    for c in candidates:
        hc    = c.get("historical_context", {})
        score = hc.get("explainability_score", c.get("score", 0))
        hook  = hc.get("suggested_hook", "")
        out.append({"title": c.get("title", ""), "score": score, "hook": hook})
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
        from main import run_phase2_for_story
        run_phase2_for_story(date, story_index)
        return f"Story {story_index + 1} approved. Script and visuals generating now.", 200
    except Exception as e:
        return f"Story {story_index + 1} approved but Phase 2 trigger failed: {e}", 500


@app.route("/approve/<date>/status")
def approval_status(date):
    approvals = load_approvals()
    return jsonify(approvals.get(date, {"approved": []}))


@app.route("/approve/<date>/auto")
def auto_approve(date):
    approvals = load_approvals()
    day_data  = approvals.get(date, {"approved": []})
    if not day_data["approved"]:
        approvals[date] = {
            "approved":  [0],
            "timestamp": datetime.datetime.now().isoformat(),
            "auto":      True,
        }
        save_approvals(approvals)
        try:
            from main import run_phase2_for_story
            run_phase2_for_story(date, 0)
            return "Auto-approved story 1. Script and visuals generating.", 200
        except Exception as e:
            return f"Auto-approve triggered but Phase 2 failed: {e}", 500
    return f"Stories already approved: {day_data['approved']}", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
