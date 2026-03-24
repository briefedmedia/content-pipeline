# pipeline_api.py -- Railway "pipeline-api" service entry point
# Start command: python pipeline_api.py
# Includes breaking news bypass/hold routes (from breaking.py) + utility endpoints
#
# Railway deployment:
#   Service: pipeline-api
#   Start command: python pipeline_api.py
#   Port: 8080 (set PORT env var in Railway or use default below)

from breaking import app  # imports Flask app with /breaking/<id>/bypass and /breaking/<id>/hold
from flask import jsonify
import drive
import os

PORT = int(os.getenv("PORT", 8080))

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
