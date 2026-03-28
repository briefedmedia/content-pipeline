"""One-off fix: Insert missing script + clips rows into Sheets for
2026-03-28_pentagon-ukraine-iran-munitions so Phase 3 can find them.

Phase 2 ran successfully but didn't call save_todays_script / save_todays_clips.
This script reads the data from Drive and inserts the missing Sheets rows.

Usage: python fix_missing_sheets_data.py
"""

import json, datetime
from drive import get_service, download_file, get_or_create_story_folder
from sheets import _get_sheet

SLUG = "2026-03-28_pentagon-ukraine-iran-munitions"
DATE = "2026-03-28"
ACCOUNT = "news"


def main():
    service = get_service()

    # 1. Download script JSON from Drive
    print("Fetching script from Drive...")
    scripts_folder = get_or_create_story_folder(SLUG, "scripts")
    script_filename = f"script_{SLUG}.json"

    results = service.files().list(
        q=f'"{scripts_folder}" in parents and name = "{script_filename}" and trashed = false',
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    script_files = results.get("files", [])

    if not script_files:
        print(f"ERROR: {script_filename} not found in Drive/scripts/{SLUG}/")
        return

    # Download to temp
    import tempfile, os
    tmp_path = os.path.join(tempfile.gettempdir(), script_filename)
    download_file(script_files[0]["id"], tmp_path)
    with open(tmp_path, encoding="utf-8") as f:
        script_data = json.load(f)
    print(f"  Loaded script: {script_data.get('title', '?')}")
    print(f"  Word count: {script_data.get('word_count', '?')}")
    print(f"  Scenes: {len(script_data.get('scenes', []))}")

    # 2. List clips from Drive
    print("\nFetching clips from Drive...")
    clips_folder = get_or_create_story_folder(SLUG, "clips")

    results = service.files().list(
        q=f'"{clips_folder}" in parents and trashed = false',
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        orderBy="name",
    ).execute()
    clip_files = results.get("files", [])

    if not clip_files:
        print(f"ERROR: No clips found in Drive/clips/{SLUG}/")
        return

    # Sort by name to ensure correct order
    clip_files.sort(key=lambda f: f["name"])

    clip_records = []
    for cf in clip_files:
        if not cf["name"].endswith(".mp4"):
            continue
        clip_records.append({
            "drive_id": cf["id"],
            "name":     cf["name"],
            "subdir":   SLUG,
        })
    print(f"  Found {len(clip_records)} clips")
    for cr in clip_records:
        print(f"    {cr['name']} -> {cr['drive_id'][:20]}...")

    # 3. Insert rows into Sheets
    print("\nInserting rows into Sheets...")
    sheet = _get_sheet()
    now = datetime.datetime.now().isoformat()

    # Script row
    sheet.append_row([now, DATE, ACCOUNT, "script", json.dumps(script_data)],
                     value_input_option="RAW")
    print(f"  [Sheets] Script row inserted for {SLUG}")

    # Clips row
    sheet.append_row([now, DATE, ACCOUNT, "clips", json.dumps(clip_records)],
                     value_input_option="RAW")
    print(f"  [Sheets] Clips row inserted ({len(clip_records)} clips)")

    print("\nDone! Phase 3 should now find the script and clips.")
    print("You can trigger Phase 3 from the dashboard.")


if __name__ == "__main__":
    main()
