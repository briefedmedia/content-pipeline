# assemble.py -- produces clean MP4, captioned MP4, and silent preview
import subprocess, os, json, datetime
from drive import upload_file, get_or_create_story_folder
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
    # Mix audio + optional music at 12% volume
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
    style = "FontName=Arial,FontSize=18,PrimaryColour=&HFFFFFF,"
    style += "OutlineColour=&H000000,Outline=2,BorderStyle=3,"
    style += "BackColour=&H40000000,Alignment=2,MarginV=80"
    return SCALE + f",subtitles={srt_path}:force_style=" + chr(39) + style + chr(39)

ENCODE_ARGS = ["-c:v","libx264","-preset","fast","-crf","23",
               "-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart"]

def _encode(video, audio, vf, output):
    subprocess.run(["ffmpeg","-y","-i",video,"-i",audio,"-vf",vf]
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

def assemble_video(clip_paths, audio_path, srt_path, title, slug=None,
                   music_path=None, story_groups=None):
    """Produce clean + captioned MP4s, upload both into the story's Drive subfolder."""
    if not slug:
        slug = datetime.date.today().isoformat() + "_story"
    slug_dir = os.path.join(TMP, slug)
    os.makedirs(slug_dir, exist_ok=True)

    trimmed, final_audio, duration = _build_base(clip_paths, audio_path, music_path, slug)
    final_folder_id = get_or_create_story_folder(slug, "final")

    # Clean MP4 (TikTok + YouTube)
    clean    = os.path.join(slug_dir, f"final_clean_{slug}.mp4")
    _encode(trimmed, final_audio, SCALE, clean)
    clean_id = upload_file(clean, "final", f"final_clean_{slug}.mp4",
                           folder_id=final_folder_id)
    print(f"Clean MP4: {get_audio_duration(clean):.1f}s saved → Drive/final/{slug}/")

    # Captioned MP4 (Instagram)
    captioned    = os.path.join(slug_dir, f"final_captioned_{slug}.mp4")
    _encode(trimmed, final_audio, CAPTION_FILTER(srt_path), captioned)
    captioned_id = upload_file(captioned, "final", f"final_captioned_{slug}.mp4",
                               folder_id=final_folder_id)
    print(f"Captioned MP4: {get_audio_duration(captioned):.1f}s saved → Drive/final/{slug}/")

    return {
        "clean":     {"path": clean,     "drive_id": clean_id},
        "captioned": {"path": captioned, "drive_id": captioned_id},
        "srt":       srt_path,
        "duration":  duration,
    }
