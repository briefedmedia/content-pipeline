# watcher.py -- runs continuously as background process
# Polls Drive/05_audio/pending/ and story subfolders every 60 seconds
# When your recording appears, fires Phase 3 and cleans up DROP_VO_HERE.txt
# Run: python watcher.py (always-on Railway service)

import time, datetime, subprocess
from drive import list_pending_recordings, delete_file
from sheets import get_todays_job
from notify import send_notification

POLL_SECONDS = 60
seen = set()

def check_for_recordings():
    pending = list_pending_recordings()
    for f in pending:
        if f["id"] in seen: continue
        seen.add(f["id"])
        name = f["name"]

        # Skip placeholder files
        if name == "DROP_VO_HERE.txt": continue

        today = datetime.date.today().isoformat()
        if today not in name: continue  # skip old recordings
        account = "news" if "news" in name else "history"

        # Extract slug: voiceover_YYYY-MM-DD_slug-keywords_account.mp3
        parts = name.replace(".mp3", "").split("_")
        if len(parts) >= 4:
            slug = f"{parts[1]}_{parts[2]}"
        else:
            slug = None

        parent_folder_id = f.get("parent_folder_id")

        print(f"New recording: {name} (account: {account}, slug: {slug})")
        job = get_todays_job(account)
        if job and job.get("phase2_status") == "success":
            print(f"Phase 2 done -- firing Phase 3 for {account} slug: {slug}")
            cmd = ["python", "main.py", "3", account, "--trigger", "file_watcher"]
            if slug:
                cmd += ["--slug", slug]
            subprocess.Popen(cmd)

            # Delete DROP_VO_HERE.txt placeholder from the same subfolder
            if parent_folder_id:
                try:
                    from drive import get_service
                    service = get_service()
                    results = service.files().list(
                        q=(f'"{parent_folder_id}" in parents and '
                           f'name = "DROP_VO_HERE.txt" and trashed = false'),
                        fields="files(id)",
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    ).execute()
                    for placeholder in results.get("files", []):
                        delete_file(placeholder["id"])
                        print(f"  Deleted DROP_VO_HERE.txt from pending/{slug}/")
                except Exception as e:
                    print(f"  Could not delete DROP_VO_HERE.txt: {e}")
        else:
            send_notification(
                title="Recording received early",
                message="Clips still generating. Phase 3 fires automatically when ready.",
                priority="normal")

if __name__ == "__main__":
    print("File watcher running -- monitoring Drive/05_audio/pending/ and subfolders")
    while True:
        try: check_for_recordings()
        except Exception as e: print(f"Watcher error: {e}")
        time.sleep(POLL_SECONDS)

# RECORDING NAMING CONVENTION:
# voiceover_YYYY-MM-DD_slug-keywords_news.mp3     e.g. voiceover_2026-03-25_trump-tariffs_news.mp3
# voiceover_YYYY-MM-DD_slug-keywords_history.mp3  e.g. voiceover_2026-03-25_ancient-rome_history.mp3
# Slug keywords shown in the preview-ready Pushover notification.
