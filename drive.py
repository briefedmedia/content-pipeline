# drive.py -- all pipeline stages import from this file
# Uses Service Account credentials (no OAuth flow required -- works on Railway)

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2 import service_account
import io, os, datetime

SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = "service_account.json"

FOLDERS = {
    "stories":   "1ZuCmxYRmYQwbMoMTIIqntvc0zMAd6aqa",
    "scripts":   "1xRupya1ro5tKjM9ef-dkQbrgbappcZ34",
    "images":    "167MQM-kopCJpZ38VPvFdq34Fgck6iyco",
    "clips":     "1mfJFxqHKYs34yTlGZxvBaFm_981tA9OS",
    "audio":     "1p2g3W7yU_mju5rOnqwJg9CAEhQjGTVsF",
    "pending":   "15-r9x5VRNdzkKsYlBiT_jQqkfK3bulXl",
    "captions":  "16F-kDmy5_obLBUBSBQBWv1IEL84QPhpe",
    "final":     "1b4hfHTy1FI6sq2neuadpLPEEvlvzhA-1",
    "published": "12LaqWIWM2OJrsWuVuCk2F6B2BhJRTmk3",
    "previews":  "1BmX3_xJkHjjTJmPF1frq3Vv_LerFCXgm",
}

def get_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)

def upload_file(local_path, folder_key, filename=None):
    if folder_key not in FOLDERS:
        raise ValueError(f"Folder key '{folder_key}' not found in FOLDERS")
    service = get_service()
    name = filename or os.path.basename(local_path)
    meta = {"name": name, "parents": [FOLDERS[folder_key]]}
    media = MediaFileUpload(local_path, resumable=True)
    f = service.files().create(body=meta, media_body=media, fields="id,name").execute()
    print(f"Uploaded: {name} ({f['id']})")
    return f["id"]

def download_file(file_id, save_path):
    service = get_service()
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(save_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    print(f"Downloaded: {save_path}")

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

if __name__ == "__main__":
    import tempfile, os
    tmp = os.path.join(tempfile.gettempdir(), "test_upload.txt")
    with open(tmp, "w") as f:
        f.write("Pipeline connection test")
    file_id = upload_file(tmp, "stories", "test_upload.txt")
    print(f"Success -- file ID: {file_id}")