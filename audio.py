# audio.py -- checks Drive pending/ for human recording first, falls back to TTS
# TTS provider hierarchy: Google Cloud TTS (primary) → Edge TTS (fallback)
import whisper, datetime, os, asyncio
from dotenv import load_dotenv
load_dotenv()
from drive import upload_file, list_pending_recordings, get_or_create_story_folder
from config import TMP, TTS_PROVIDER, GOOGLE_TTS_VOICE, EDGE_TTS_VOICE

# Google Cloud TTS setup
# On Railway, write service account JSON from env var to temp file
_sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
if _sa_json:
    import tempfile
    _tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    _tmp.write(_sa_json)
    _tmp.close()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _tmp.name
else:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS",
        r"C:\Users\micah\OneDrive\Documents\AIUsedRight\ContentPipeline\service_account.json"
    )
from google.cloud import texttospeech


def check_for_human_recording(today, account_type, slug, slug_dir):
    """Check Drive pending folder for a recording matching today and account."""
    local_path = os.path.join(slug_dir, f"voiceover_{today}_{account_type}.mp3")
    pending    = list_pending_recordings()
    for f in pending:
        if today in f["name"] and account_type in f["name"]:
            from drive import get_service
            from googleapiclient.http import MediaIoBaseDownload
            import io
            service = get_service()
            req     = service.files().get_media(fileId=f["id"])
            with open(local_path, "wb") as fh:
                dl   = MediaIoBaseDownload(fh, req)
                done = False
                while not done:
                    _, done = dl.next_chunk()
            print(f"  Human recording found for {today} {account_type} -- using your voice")
            return local_path
    return None


def _generate_tts_google(script_text, account_type, today, slug_dir):
    """Generate TTS using Google Cloud Neural2 voices -- free tier up to 1M chars/month."""
    print(f"  Generating TTS via Google Cloud ({account_type} voice)...")
    client    = texttospeech.TextToSpeechClient()
    voice_name = GOOGLE_TTS_VOICE[account_type]

    synthesis_input = texttospeech.SynthesisInput(text=script_text)
    voice           = texttospeech.VoiceSelectionParams(
        language_code = "en-US",
        name          = voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding   = texttospeech.AudioEncoding.MP3,
        speaking_rate    = 0.95,   # slightly slower than default -- better for news
        pitch            = 0.0,
        volume_gain_db   = 0.0,
        effects_profile_id = ["headphone-class-device"],
    )

    response   = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    local_path = os.path.join(slug_dir, f"voiceover_{today}_{account_type}.mp3")
    with open(local_path, "wb") as f:
        f.write(response.audio_content)
    print(f"  Google TTS complete: {len(script_text)} characters used")
    return local_path


async def _generate_tts_edge_async(script_text, account_type, today, slug_dir):
    """Generate TTS using Microsoft Edge neural voices -- free, no account needed."""
    import edge_tts
    voice      = EDGE_TTS_VOICE[account_type]
    local_path = os.path.join(slug_dir, f"voiceover_{today}_{account_type}.mp3")
    print(f"  Generating TTS via Edge TTS ({voice})...")
    communicate = edge_tts.Communicate(script_text, voice)
    await communicate.save(local_path)
    return local_path


def _generate_tts_edge(script_text, account_type, today, slug_dir):
    """Sync wrapper for Edge TTS async call."""
    return asyncio.run(
        _generate_tts_edge_async(script_text, account_type, today, slug_dir)
    )


def generate_tts(script_text, account_type, today, slug_dir):
    """
    TTS with automatic fallback.
    Primary: Google Cloud Neural2 (free tier)
    Fallback: Edge TTS (always free, no account)
    """
    if TTS_PROVIDER == "google":
        try:
            return _generate_tts_google(script_text, account_type, today, slug_dir)
        except Exception as e:
            print(f"  Google TTS failed: {e}")
            print(f"  Falling back to Edge TTS...")
            return _generate_tts_edge(script_text, account_type, today, slug_dir)
    else:
        return _generate_tts_edge(script_text, account_type, today, slug_dir)


def generate_captions(audio_path, today, account_type, slug, slug_dir):
    model  = whisper.load_model("small")
    result = model.transcribe(audio_path, word_timestamps=True)
    srt_path = os.path.join(slug_dir, f"captions_{today}_{account_type}.srt")

    # Build word-level SRT -- one word per caption entry
    entries = []
    for seg in result["segments"]:
        words = seg.get("words", [])
        if not words:
            # Fallback: no word timestamps, use segment as single entry
            entries.append((seg["start"], seg["end"], seg["text"].strip()))
        else:
            for word in words:
                text = word["word"].strip()
                if text:
                    entries.append((word["start"], word["end"], text))

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(entries):
            s = _format_time(start)
            e = _format_time(end)
            f.write(f"{i+1}\n{s} --> {e}\n{text}\n\n")
    captions_folder_id = get_or_create_story_folder(slug, "captions")
    upload_file(srt_path, "captions", folder_id=captions_folder_id)
    print(f"  Captions saved: {srt_path}")
    return srt_path


def _format_time(seconds):
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def run_audio(script_data, account_type="history"):
    today    = datetime.date.today().isoformat()
    slug     = script_data.get("slug") or f"{today}_{account_type}"
    slug_dir = os.path.join(TMP, slug)
    os.makedirs(slug_dir, exist_ok=True)

    # Priority 1 -- human recording dropped in Drive/05_audio/pending/
    audio_path = check_for_human_recording(today, account_type, slug, slug_dir)

    # Priority 2 -- TTS (Google primary, Edge fallback)
    if audio_path is None:
        audio_path = generate_tts(script_data["script"], account_type, today, slug_dir)

    # Upload to Drive/05_audio/slug/
    audio_folder_id = get_or_create_story_folder(slug, "audio")
    upload_file(audio_path, "audio", folder_id=audio_folder_id)

    # Generate captions from audio
    srt_path = generate_captions(audio_path, today, account_type, slug, slug_dir)
    return audio_path, srt_path


if __name__ == "__main__":
    import json, glob

    today   = datetime.date.today().isoformat()
    pattern = os.path.join(TMP, f"{today}_*", f"script_{today}_*.json")
    matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    if not matches:
        print("No script found -- run script.py first")
    else:
        with open(matches[0], encoding="utf-8") as f:
            script_data = json.load(f)

        print(f"Loaded script: {script_data['title']}")
        print(f"Slug: {script_data['slug']}")
        print(f"TTS provider: {TTS_PROVIDER}\n")

        audio_path, srt_path = run_audio(script_data, account_type="news")

        print(f"\nAudio:    {audio_path}")
        print(f"Captions: {srt_path}")
        print(f"Check Drive/05_audio/{script_data['slug']}/ to confirm upload")