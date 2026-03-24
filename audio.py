# audio.py -- checks Drive pending/ for human recording first, falls back to TTS
import whisper, datetime, os
from elevenlabs.client import ElevenLabs
from drive import upload_file, list_pending_recordings

el_client = ElevenLabs(api_key=os.getenv("sk_f0af92a3f700b1b82a4668d223f1082d95fe30613a230b60"))

VOICE_IDS = {
    "history": "pNInz6obpgDQGcFmaJgB",  # Adam -- verify at elevenlabs.io/voice-library
    "news":    "21m00Tcm4TlvDq8ikWAM",  # Rachel (TTS fallback for news only)
}

def check_for_human_recording(today, account_type):
    """Check Drive pending folder for a recording matching today and account."""
    local_path = f"/tmp/voiceover_{today}_{account_type}.mp3"
    pending = list_pending_recordings()
    for f in pending:
        if today in f["name"] and account_type in f["name"]:
            # Download it
            from drive import get_service
            from googleapiclient.http import MediaIoBaseDownload
            import io
            service = get_service()
            req = service.files().get_media(fileId=f["id"])
            with open(local_path, "wb") as fh:
                dl = MediaIoBaseDownload(fh, req)
                done = False
                while not done: _, done = dl.next_chunk()
            print(f"Human recording found for {today} {account_type} -- using your voice")
            return local_path
    return None

def generate_tts(script_text, account_type, today):
    voice_id = VOICE_IDS[account_type]
    print(f"No human recording found -- generating TTS ({account_type} voice)")
    audio = el_client.generate(
        text=script_text, voice=voice_id, model="eleven_multilingual_v2")
    local_path = f"/tmp/voiceover_{today}_{account_type}.mp3"
    with open(local_path, "wb") as f:
        for chunk in audio: f.write(chunk)
    return local_path

def generate_captions(audio_path, today, account_type):
    model = whisper.load_model("small")
    result = model.transcribe(audio_path)
    srt_path = f"/tmp/captions_{today}_{account_type}.srt"
    with open(srt_path, "w") as f:
        for i, seg in enumerate(result["segments"]):
            s = format_time(seg["start"])
            e = format_time(seg["end"])
            f.write(f"{i+1}\n{s} --> {e}\n{seg['text'].strip()}\n\n")
    upload_file(srt_path, "captions")
    return srt_path

def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def run_audio(script_data, account_type="history"):
    today = datetime.date.today().isoformat()
    audio_path = check_for_human_recording(today, account_type)
    if audio_path is None:
        audio_path = generate_tts(script_data["script"], account_type, today)
    upload_file(audio_path, "audio")
    srt_path = generate_captions(audio_path, today, account_type)
    return audio_path, srt_path
