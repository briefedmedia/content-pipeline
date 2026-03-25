# drive.py -- all pipeline stages import from this file
# Uses Service Account credentials (no OAuth flow required -- works on Railway)

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2 import service_account
import io, os, datetime

import json, tempfile
SCOPES = ["https://www.googleapis.com/auth/drive"]

def _get_service_account_file():
    """
    On Railway: write GOOGLE_SERVICE_ACCOUNT_JSON env var to a temp file.
    Locally: use service_account.json file directly.
    """
    json_content = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if json_content:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(json_content)
        tmp.close()
        return tmp.name
    return "service_account.json"

SERVICE_ACCOUNT_FILE = _get_service_account_file()

FOLDERS = {
    "stories":   "1ZuCmxYRmYQwbMoMTIIqntvc0zMAd6aqa",
    "scripts":   "1W-wvDHynt_m4MSPAXDAY-j7CsGiCq93L",
    "images":    "14RFZr08yyxoGHaX0vLJaA8HjhBnFPMh0",
    "clips":     "1JNVMehfRq4-8NdXWhDCw-eUD5um6L9iC",
    "audio":     "1zn8eH2vh3IQ_2dVNmn7EpA8yr5buXDog",
    "pending":   "1NU3EkuQKibOF-dx6KzoiL8zx_jYajFkg",
    "captions":  "1lmT4b92i9DY6Lixqrv1TYUmaPKgWez-G",
    "final":     "1-dvCxRypjLTMN7p_uRpthBidlsdpBljJ",
    "published": "18d2S94_SmmJb_gho9y5w_CcqiEsMpFbE",
    "previews":  "1eQszd5rLV0r3DfzL9h_1z8YOVj3R9Wtq",
}

def get_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)

def get_or_create_story_folder(slug, category):
    """Find or create a slug-named subfolder inside the given category folder.

    For story-specific files:  category = "scripts" / "images" / "clips" / etc.
    For daily discovery files: pass the date string as slug, category = "stories"

    Returns the Drive folder ID for that subfolder.
    All API calls use supportsAllDrives=True.
    """
    service   = get_service()
    parent_id = FOLDERS[category]

    # Search for an existing subfolder with this exact name
    results = service.files().list(
        q=(
            f'"{parent_id}" in parents and '
            f'name = "{slug}" and '
            f'mimeType = "application/vnd.google-apps.folder" and '
            f'trashed = false'
        ),
        fields                    = "files(id, name)",
        supportsAllDrives         = True,
        includeItemsFromAllDrives = True,
    ).execute()

    files = results.get("files", [])
    if files:
        return files[0]["id"]

    # Subfolder does not exist yet — create it
    meta   = {
        "name":     slug,
        "mimeType": "application/vnd.google-apps.folder",
        "parents":  [parent_id],
    }
    folder = service.files().create(
        body              = meta,
        fields            = "id",
        supportsAllDrives = True,
    ).execute()
    print(f"Created Drive subfolder: {category}/{slug} (id: {folder['id']})")
    return folder["id"]

def upload_file(local_path, folder_key, filename=None, folder_id=None):
    """Upload a file to Drive.

    folder_id (optional): pass the story subfolder ID returned by
    get_or_create_story_folder() to land the file inside the slug subfolder.
    When omitted the file goes into the root category folder as before.
    """
    service = get_service()
    name    = filename or os.path.basename(local_path)
    parent  = folder_id if folder_id else FOLDERS[folder_key]
    meta    = {"name": name, "parents": [parent]}
    media   = MediaFileUpload(local_path, resumable=True)
    f = service.files().create(
        body              = meta,
        media_body        = media,
        fields            = "id,name",
        supportsAllDrives = True,
    ).execute()
    label = f"{folder_key}/{os.path.basename(os.path.dirname(local_path))}" if folder_id else folder_key
    print(f"Uploaded {name} → Drive/{label} (id: {f['id']})")
    return f["id"]

def download_file(file_id, local_path):
    service = get_service()
    req = service.files().get_media(
        fileId=file_id,
        supportsAllDrives=True       # ← add this line
    )
    with open(local_path, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            _, done = dl.next_chunk()

def list_files(folder_key):
    if folder_key not in FOLDERS:
        raise ValueError(f"Folder key '{folder_key}' not found in FOLDERS")
    service = get_service()
    folder_id = FOLDERS[folder_key]
    results = service.files().list(
        q=f'"{folder_id}" in parents and trashed=false',
        fields="files(id, name, createdTime)"
    ).execute()
    return results.get("files", [])

def list_pending_recordings():
    """List files in 05_audio/pending/ for the file watcher."""
    service = get_service()
    folder_id = FOLDERS["pending"]
    results = service.files().list(
        q=f'"{folder_id}" in parents and trashed=false',
        fields="files(id, name, createdTime)"
    ).execute()
    return results.get("files", [])

def list_drive_clips(date, account_type):
    """List clip files for a given date and account type from the clips folder."""
    service = get_service()
    folder_id = FOLDERS["clips"]
    results = service.files().list(
        q=f'"{folder_id}" in parents and trashed=false and name contains "clip_{date}"',
        orderBy="name",
        fields="files(id, name, createdTime)"
    ).execute()
    files = results.get("files", [])
    # Return as clip dicts -- path will be set when downloaded
    return [{"drive_id": f["id"], "name": f["name"], "path": None} for f in files]

def make_public_url(file_id):
    """Temporarily make a Drive file public for Instagram API upload."""
    service = get_service()
    service.permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"}
    ).execute()
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    print("Public URL created")
    return url

def delete_file(file_id):
    service = get_service()
    service.files().delete(fileId=file_id).execute()
    print("Deleted:", file_id)