# recap.py -- Sunday "This week in 90 seconds" -- uses existing clips, no new generation
import anthropic, json, datetime
from drive  import upload_file, list_drive_clips
from sheets import get_weeks_jobs
from audio  import run_audio
from assemble import assemble_video
from publish import publish_all
from notify import send_notification

RECAP_PROMPT = """Write a weekly news recap (max 225 words, min 150).
You will receive this weeks video scripts.
Open with: "This week..." and a strong through-line connecting stories.
Cover each story in 1-3 sentences. Use transitions: Meanwhile, Closer to home...
Close with one sentence framing the week as a whole.
TONE: Brisk, conversational, highlight-reel energy. More upbeat than daily videos.
Return JSON: {"script":"...", "title":"This Week: [2-4 words]",
 "word_count":N, "story_order":[...], "story_seconds":[...]}"""

def select_recap_clips(weekly_jobs, story_seconds):
    """Pull best existing clips -- zero new Runway/Pika cost."""
    recap_clips = []
    for job, seconds in zip(weekly_jobs, story_seconds):
        count = max(1, round(seconds / 5))
        all_clips = list_drive_clips(job["date"], job["account_type"])
        if len(all_clips) <= count:
            selected = all_clips
        else:
            indices = [0]
            if count > 2:
                step = len(all_clips) / (count - 1)
                indices += [round(i * step) for i in range(1, count - 1)]
            indices.append(len(all_clips) - 1)
            selected = [all_clips[i] for i in sorted(set(indices))]
        recap_clips.append({"title": job["title"], "clips": selected, "seconds": seconds})
    return recap_clips

def run_weekly_recap():
    client = anthropic.Anthropic()
    weekly_jobs = get_weeks_jobs()
    if not weekly_jobs:
        print("No videos this week -- skipping recap"); return
    week_scripts = [{"title": j["title"], "script": j.get("script","")} for j in weekly_jobs]
    msg = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1000,
        system=RECAP_PROMPT,
        messages=[{"role":"user","content":json.dumps(week_scripts)}])
    recap_data = json.loads(msg.content[0].text)
    recap_data["account_type"] = "news"
    clip_groups = select_recap_clips(weekly_jobs, recap_data["story_seconds"])
    all_clips = [c for group in clip_groups for c in group["clips"]]
    audio_path, srt_path = run_audio(recap_data, "news")
    outputs = assemble_video(all_clips, audio_path, srt_path, recap_data["title"])
    publish_all(outputs, srt_path, recap_data, "news")
    print(f"Weekly recap complete: {recap_data['title']}")
