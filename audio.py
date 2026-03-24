# audio.py -- checks Drive pending/ for human recording first, falls back to TTS
import whisper, datetime, os
from elevenlabs.client import ElevenLabs
from drive import upload_file, list_pending_recordings, get_or_create_story_folder
from config import TMP

el_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

VOICE_IDS = {
    "history": "pNInz6obpgDQGcFmaJgB",  # Adam -- verify at elevenlabs.io/voice-library
    "news":    "21m00Tcm4TlvDq8ikWAM",  # Rachel (TTS fallback for news only)
}

def check_for_human_recording(today, account_type, slug, slug_dir):
    """Check Drive pending folder for a recording matching today and account."""
    local_path = os.path.join(slug_dir, f"voiceover_{today}_{account_type}.mp3")
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

def generate_tts(script_text, account_type, today, slug_dir):
    voice_id = VOICE_IDS[account_type]
    print(f"No human recording found -- generating TTS ({account_type} voice)")
    audio      = el_client.generate(
        text=script_text, voice=voice_id, model="eleven_multilingual_v2")
    local_path = os.path.join(slug_dir, f"voiceover_{today}_{account_type}.mp3")
    with open(local_path, "wb") as f:
        for chunk in audio: f.write(chunk)
    return local_path

def generate_captions(audio_path, today, account_type, slug, slug_dir):
    model    = whisper.load_model("small")
    result   = model.transcribe(audio_path)
    srt_path = os.path.join(slug_dir, f"captions_{today}_{account_type}.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(result["segments"]):
            s = format_time(seg["start"])
            e = format_time(seg["end"])
            f.write(f"{i+1}\n{s} --> {e}\n{seg['text'].strip()}\n\n")
    captions_folder_id = get_or_create_story_folder(slug, "captions")
    upload_file(srt_path, "captions", folder_id=captions_folder_id)
    return srt_path

def format_time(seconds):
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def run_audio(script_data, account_type="history"):
    today = datetime.date.today().isoformat()
    # Slug flows from script_data -- single source of truth
    # Fallback for recap or other callers that may not have a slug yet
    slug     = script_data.get("slug") or f"{today}_{account_type}"
    slug_dir = os.path.join(TMP, slug)
    os.makedirs(slug_dir, exist_ok=True)

    audio_path = check_for_human_recording(today, account_type, slug, slug_dir)
    if audio_path is None:
        audio_path = generate_tts(script_data["script"], account_type, today, slug_dir)

    audio_folder_id = get_or_create_story_folder(slug, "audio")
    upload_file(audio_path, "audio", folder_id=audio_folder_id)

    srt_path = generate_captions(audio_path, today, account_type, slug, slug_dir)
    return audio_path, srt_path
