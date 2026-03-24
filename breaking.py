# breaking.py -- Flask server for bypass/hold decision via tap links
# Run as always-on Railway service: flask run --host 0.0.0.0

import os, json, threading
from flask import Flask
from script  import write_script, audit_bias, quality_check
from images  import run_image_generation
from clips   import run_clip_generation
from sheets  import create_breaking_job, update_breaking_job
from notify  import send_notification
from config  import get_style

app = Flask(__name__)
SERVER_URL = os.getenv("SERVER_URL")  # e.g. https://yourapp.railway.app

def handle_breaking(story, urgency, account_type):
    script = write_script(story, account_type)
    if account_type == "news": script = audit_bias(script)
    script = quality_check(script)
    job_id = create_breaking_job(story, script, account_type)
    # Start Phase 2 immediately -- clips take time regardless of VO decision
    def generate_visuals():
        imgs  = run_image_generation(script, get_style(account_type))
        clips = run_clip_generation(imgs, account_type)
        update_breaking_job(job_id, {"clips": clips, "phase2": "done"})
    threading.Thread(target=generate_visuals).start()
    bypass_url = f"{SERVER_URL}/breaking/{job_id}/bypass"
    hold_url   = f"{SERVER_URL}/breaking/{job_id}/hold"
    send_notification(
        title    = f"BREAKING ({urgency}/10): {story['title']}",
        message  = (f"{script['script'][:300]}...\n\n"
                    "Visuals generating now.\n\n"
                    f"TAP TO USE TTS (post faster): {bypass_url}\n"
                    f"TAP TO HOLD (record your VO): {hold_url}\n\n"
                    "No response in 2 hours = HOLD"),
        priority = "breaking")

@app.route("/breaking/<job_id>/bypass")
def bypass(job_id):
    update_breaking_job(job_id, {"decision": "tts"})
    import subprocess
    subprocess.Popen(["python","main.py","3","news","--trigger","breaking_tts"])
    return "TTS pipeline triggered. Video will post at next optimal time.", 200

@app.route("/breaking/<job_id>/hold")
def hold(job_id):
    update_breaking_job(job_id, {"decision": "hold"})
    return "Job held. Drop your VO in Drive/pending/ when ready.", 200
