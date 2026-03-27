import subprocess, os, json, datetime
from drive import upload_file, get_or_create_story_folder
from ambient import get_ambient_for_scenes, AMBIENT_VOLUME
from config import TMP


def get_audio_duration(path):
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
        capture_output=True, text=True)
    return float(json.loads(result.stdout)["streams"][0]["duration"])


def create_clip_list(clip_paths, slug=None):
    """Write an ffmpeg concat list file into the slug subdir (or TMP root as fallback)."""
    if slug:
        list_file = os.path.join(TMP, slug, "clips.txt")
    else:
        list_file = os.path.join(TMP, "clips.txt")
    with open(list_file, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{clip['path']}'\n")
    return list_file


def _mix_ambient(clip_paths, ambient_paths, slug):
    """
    For each clip that has a matching ambient track, produce a new clip
    with ambient mixed in at low volume. Returns updated clip_paths list
    pointing to ambient-mixed versions where available.
    Falls back to original clip silently if mix fails.
    """
    if not any(p for p in ambient_paths if p):
        print("  No ambient tracks available -- skipping ambient mix")
        return clip_paths

    slug_dir         = os.path.join(TMP, slug)
    mixed_clip_paths = []

    for i, (clip, ambient) in enumerate(zip(clip_paths, ambient_paths)):
        if not ambient or not os.path.exists(ambient):
            mixed_clip_paths.append(clip)
            continue

        mixed_path = os.path.join(slug_dir, f"clip_ambient_{i:02d}.mp4")
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", clip["path"],
                "-i", ambient,
                "-filter_complex",
                f"[1:a]volume={AMBIENT_VOLUME}[amb];[0:a][amb]amix=inputs=2:duration=first[out]",
                "-map", "0:v", "-map", "[out]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                mixed_path
            ], check=True, capture_output=True)
            print(f"  Clip {i+1}: ambient mixed in")
            mixed_clip_paths.append({**clip, "path": mixed_path})
        except Exception as e:
            print(f"  Clip {i+1}: ambient mix failed ({e}) -- using original")
            mixed_clip_paths.append(clip)

    return mixed_clip_paths


def _build_base(clip_paths, audio_path, music_path, slug):
    """Concatenate clips, trim to audio length, optionally mix in music."""
    slug_dir       = os.path.join(TMP, slug)
    list_file      = create_clip_list(clip_paths, slug)
    audio_duration = get_audio_duration(audio_path)
    print(f"Audio: {audio_duration:.1f}s -- video will match exactly")

    # Concatenate clips
    concat = os.path.join(slug_dir, f"concat_{slug}.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", list_file, "-c", "copy", concat], check=True)

    # Trim to audio duration
    trimmed = os.path.join(slug_dir, f"trimmed_{slug}.mp4")
    subprocess.run(["ffmpeg", "-y", "-i", concat,
                    "-t", str(audio_duration), "-c", "copy", trimmed], check=True)

    # Mix audio + optional background music at 12% volume
    if music_path:
        mixed = os.path.join(slug_dir, f"mixed_{slug}.aac")
        subprocess.run(["ffmpeg", "-y", "-i", audio_path, "-i", music_path,
            "-filter_complex",
            "[0:a]volume=1.0[vo];[1:a]volume=0.12[bg];[vo][bg]amix=inputs=2:duration=first[out]",
            "-map", "[out]", mixed], check=True)
        final_audio = mixed
    else:
        final_audio = audio_path

    return trimmed, final_audio, audio_duration


SCALE = ("scale=1080:1920:force_original_aspect_ratio=decrease,"
         "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black")


def CAPTION_FILTER(srt_path):
    if os.name == "nt":
        # FFmpeg subtitles filter on Windows: forward slashes, escaped drive colon
        srt_escaped = srt_path.replace("\\", "/")
        srt_escaped = srt_escaped.replace(":/", "\\:/")
    else:
        srt_escaped = srt_path
    style = "FontName=Arial,FontSize=16,PrimaryColour=&HFFFFFF,"
    style += "OutlineColour=&H000000,Outline=2,BorderStyle=3,"
    style += "BackColour=&H40000000,Alignment=2,MarginV=350"
    return SCALE + f",subtitles='{srt_escaped}':force_style=" + chr(39) + style + chr(39)


ENCODE_ARGS = ["-c:v", "libx264", "-preset", "fast", "-crf", "23",
               "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart"]


def _encode(video, audio, vf, output):
    subprocess.run(["ffmpeg", "-y", "-i", video, "-i", audio, "-vf", vf]
                   + ENCODE_ARGS + [output], check=True)


def assemble_silent_preview(clip_paths, title, slug=None):
    """Silent rough cut for VO recording reference. No audio, no captions.
    slug is required for slug-based path; falls back to today's date if omitted.
    """
    if not slug:
        slug = datetime.date.today().isoformat() + "_preview"
    slug_dir  = os.path.join(TMP, slug)
    os.makedirs(slug_dir, exist_ok=True)
    list_file = create_clip_list(clip_paths, slug)
    output    = os.path.join(slug_dir, f"preview_{slug}.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-vf", SCALE,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-an", "-movflags", "+faststart", output], check=True)
    return output

def assemble_shorts(clean_path, audio_path, srt_path, slug, script_data=None):
    """
    Produce a YouTube Shorts version by trimming the existing clean MP4.
    No new generation -- reuses clean_path, trims to shorts_estimated_seconds.
    Returns local path, Drive ID, and Shorts-specific SRT path.
    """
    slug_dir      = os.path.join(TMP, slug)
    shorts_path   = os.path.join(slug_dir, f"final_shorts_{slug}.mp4")
    shorts_folder = get_or_create_story_folder(slug, "final")

    # Get target duration from script_data, default to 58 seconds
    target_secs = 58
    if script_data and script_data.get("shorts_estimated_seconds"):
        target_secs = min(script_data["shorts_estimated_seconds"], 58)
    print(f"  Assembling Shorts cut ({target_secs}s)...")

    # Generate Shorts TTS from shorts_script if available
    shorts_audio = audio_path  # fallback to full audio
    if script_data and script_data.get("shorts_script"):
        import datetime
        from audio import generate_tts
        today             = datetime.date.today().isoformat()
        shorts_audio_path = os.path.join(slug_dir, f"voiceover_{slug}_shorts.mp3")
        try:
            shorts_audio = generate_tts(
                script_data["shorts_script"], "news", today, slug_dir
            )
            print(f"  Shorts TTS generated")
        except Exception as e:
            print(f"  Shorts TTS failed ({e}) -- trimming full audio instead")
            shorts_audio = audio_path

    # Generate Shorts-specific word-level SRT from Shorts audio
    shorts_srt = srt_path  # fallback to full SRT
    try:
        import whisper
        from audio import _format_time
        model   = whisper.load_model("small")
        result  = model.transcribe(shorts_audio, word_timestamps=True)
        shorts_srt = os.path.join(slug_dir, f"captions_{slug}_shorts.srt")
        entries = []
        for seg in result["segments"]:
            for word in seg.get("words", []):
                text = word["word"].strip()
                if text:
                    entries.append((word["start"], word["end"], text))
        with open(shorts_srt, "w", encoding="utf-8") as f:
            for i, (start, end, text) in enumerate(entries):
                f.write(f"{i+1}\n{_format_time(start)} --> {_format_time(end)}\n{text}\n\n")
        print(f"  Shorts captions generated: {len(entries)} words")
    except Exception as e:
        print(f"  Shorts captions failed ({e}) -- using full SRT")
        shorts_srt = srt_path

    # Get actual shorts audio duration
    shorts_duration = min(get_audio_duration(shorts_audio), 58)

    # Trim clean video to shorts duration
    trimmed_shorts = os.path.join(slug_dir, f"trimmed_shorts_{slug}.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", clean_path,
        "-t", str(shorts_duration),
        "-c", "copy", trimmed_shorts
    ], check=True, capture_output=True)

    # Encode with Shorts audio and Shorts-specific captions
    _encode(trimmed_shorts, shorts_audio, CAPTION_FILTER(shorts_srt), shorts_path)

    shorts_id = upload_file(
        shorts_path, "final", f"final_shorts_{slug}.mp4",
        folder_id=shorts_folder
    )
    print(f"  Shorts MP4: {shorts_duration:.1f}s saved → Drive/final/{slug}/")
    return {"path": shorts_path, "drive_id": shorts_id, "srt_path": shorts_srt}

def _stretch_clips(clip_paths, ratio, slug):
    """Apply time-stretch to middle clips only; cap ratio to [0.90, 1.15].

    Returns a new list of clip paths (stretched files saved alongside originals).
    Falls back to originals on any FFmpeg error.
    """
    capped = max(0.90, min(1.15, ratio))
    if abs(capped - 1.0) < 0.01:
        return clip_paths   # no meaningful stretch needed

    slug_dir    = os.path.join(TMP, slug)
    n           = len(clip_paths)
    # Stretch middle scenes first (index 1 through n-2), protect hook and kicker
    stretch_idx = list(range(1, n - 1)) if n > 2 else list(range(n))
    new_paths   = list(clip_paths)

    for i in stretch_idx:
        src  = clip_paths[i]["path"] if isinstance(clip_paths[i], dict) else clip_paths[i]
        base = os.path.splitext(os.path.basename(src))[0]
        dst  = os.path.join(slug_dir, f"{base}_stretched.mp4")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", src,
                 "-vf", f"setpts={capped:.4f}*PTS",
                 "-af", f"atempo={1/capped:.4f}",
                 dst],
                check=True, capture_output=True
            )
            if isinstance(clip_paths[i], dict):
                new_paths[i] = {**clip_paths[i], "path": dst}
            else:
                new_paths[i] = dst
        except Exception as e:
            print(f"  Stretch failed for clip {i+1} ({e}) -- using original")

    return new_paths


def assemble_video(clip_paths, audio_path, srt_path, title, slug=None,
                   music_path=None, story_groups=None, script_data=None,
                   force_assemble=False):
    """Produce clean + captioned MP4s, upload both into the story's Drive subfolder.

    script_data is optional -- if provided, per-scene ambient audio is searched
    and mixed, and smart VO sync is applied (mismatch > 15s aborts unless
    force_assemble=True).
    """
    if not slug:
        slug = datetime.date.today().isoformat() + "_story"
    slug_dir = os.path.join(TMP, slug)
    os.makedirs(slug_dir, exist_ok=True)

    # Smart VO sync -- compare actual VO duration to script estimate
    if script_data and not force_assemble:
        est_seconds = script_data.get("estimated_seconds")
        if est_seconds:
            from notify import notify_vo_mismatch
            vo_duration = get_audio_duration(audio_path)
            gap         = abs(vo_duration - est_seconds)
            if gap > 15:
                print(f"  VO mismatch: {vo_duration:.0f}s vs target {est_seconds:.0f}s "
                      f"(gap {gap:.0f}s > 15s) -- aborting assembly")
                notify_vo_mismatch(title, script_data.get("account_type", "news"),
                                   vo_duration, est_seconds)
                return None
            # Apply per-clip stretch to close the gap
            ratio = vo_duration / est_seconds
            if abs(ratio - 1.0) >= 0.01:
                print(f"  Applying clip stretch ratio {ratio:.3f} (VO {vo_duration:.0f}s "
                      f"vs target {est_seconds:.0f}s)")
                clip_paths = _stretch_clips(clip_paths, ratio, slug)

    # Per-scene ambient mix -- fails gracefully per clip
    if script_data:
        scenes        = script_data.get("scenes", [])
        print(f"Searching ambient audio for {len(scenes)} scenes...")
        ambient_paths = get_ambient_for_scenes(scenes, clip_paths, slug)
        clip_paths    = _mix_ambient(clip_paths, ambient_paths, slug)

    trimmed, final_audio, duration = _build_base(clip_paths, audio_path, music_path, slug)
    final_folder_id = get_or_create_story_folder(slug, "final")

    # Clean MP4 (TikTok + YouTube)
    clean    = os.path.join(slug_dir, f"final_clean_{slug}.mp4")
    _encode(trimmed, final_audio, SCALE, clean)
    clean_id = upload_file(clean, "final", f"final_clean_{slug}.mp4",
                           folder_id=final_folder_id)
    print(f"Clean MP4: {get_audio_duration(clean):.1f}s saved → Drive/final/{slug}/")

    # Captioned MP4 (Instagram)
    captioned = os.path.join(slug_dir, f"final_captioned_{slug}.mp4")
    _encode(trimmed, final_audio, CAPTION_FILTER(srt_path), captioned)
    captioned_id = upload_file(captioned, "final", f"final_captioned_{slug}.mp4",
                               folder_id=final_folder_id)
    print(f"Captioned MP4: {get_audio_duration(captioned):.1f}s saved → Drive/final/{slug}/")

    # Shorts cut -- reuses clean MP4, trims to 58s max, generates Shorts TTS
    shorts = None
    if script_data and script_data.get("shorts_script"):
        try:
            shorts = assemble_shorts(clean, audio_path, srt_path, slug, script_data)
        except Exception as e:
            print(f"  Shorts assembly failed ({e}) -- skipping")

    return {
        "clean":     {"path": clean,     "drive_id": clean_id},
        "captioned": {"path": captioned, "drive_id": captioned_id},
        "shorts":    shorts,
        "srt":       srt_path,
        "duration":  duration,
    }

if __name__ == "__main__":
    import json, glob
    from config import TMP

    today   = datetime.date.today().isoformat()
    pattern = os.path.join(TMP, f"{today}_*", f"script_{today}_*.json")
    matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    if not matches:
        print("No script found -- run script.py first")
    else:
        with open(matches[0], encoding="utf-8") as f:
            script_data = json.load(f)

        slug     = script_data["slug"]
        slug_dir = os.path.join(TMP, slug)

        # Reconstruct clip_paths from local files
        clip_files = sorted(glob.glob(os.path.join(slug_dir, "clip_*.mp4")))
        if not clip_files:
            print(f"No clips found in {slug_dir} -- run clips.py first")
        else:
            clip_paths = [{"path": p, "drive_id": None, "slug": slug} for p in clip_files]

            # Find audio and captions
            audio_path = os.path.join(slug_dir, f"voiceover_{today}_news.mp3")
            srt_path   = os.path.join(slug_dir, f"captions_{today}_news.srt")

            if not os.path.exists(audio_path):
                print(f"No audio found at {audio_path} -- run audio.py first")
            elif not os.path.exists(srt_path):
                print(f"No captions found at {srt_path} -- run audio.py first")
            else:
                print(f"Found {len(clip_paths)} clips for {slug}")
                print(f"Audio: {audio_path}")
                print(f"Captions: {srt_path}")
                print(f"Assembling...\n")

                result = assemble_video(
                    clip_paths  = clip_paths,
                    audio_path  = audio_path,
                    srt_path    = srt_path,
                    title       = script_data["title"],
                    slug        = slug,
                    script_data = script_data,
                )

                print(f"\nDone.")
                print(f"Clean MP4:     {result['clean']['path']}")
                print(f"Captioned MP4: {result['captioned']['path']}")
                print(f"Duration:      {result['duration']:.1f}s")
                print(f"Check Drive/07_final/{slug}/ to confirm upload")