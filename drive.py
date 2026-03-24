# drive.py
# Google Drive utility for ContentPipeline using headless OAuth2

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import io
import os
import datetime

# =========================
# CONFIG
# =========================

SCOPES = ["https://www.googleapis.com/auth/drive"]
CLIENT_SECRET_FILE = "client_secret.json"  # downloaded from Google Cloud
TOKEN_FILE = "token.json"                  # cached token for headless runs

# Replace these with folder IDs from your personal Drive
FOLDERS = {
    "stories":   "1-fR7hpfyl6HMCVORNHZv4n2G-IrzbcG-",
    "scripts":   "1xRupya1ro5tKjM9ef-dkQbrgbappcZ34",
    "images":    "167MQM-kopCJpZ38VPvFdq34Fgck6iyco",
    "clips":     "1mfJFxqHKYs34yTlGZxvBaFm_981tA9OS",
    "audio":     "1p2g3W7yU_mju5rOnqwJg9CAEhQjGTVsF",
    "pending": "15-r9x5VRNdzkKsYlBiT_jQqkfK3bulXl",
    "captions":  "16F-kDmy5_obLBUBSBQBWv1IEL84QPhpe",
    "final":     "1b4hfHTy1FI6sq2neuadpLPEEvlvzhA-1",
    "published": "12LaqWIWM2OJrsWuVuCk2F6B2BhJRTmk3",
    "previews":  "1BmX3_xJkHjjTJmPF1frq3Vv_LerFCXgm",
}

# =========================
# SERVICE CONNECTION
# =========================

def get_service():
    """Headless OAuth2 service using saved token.json"""
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError(
            "token.json not found! Run OAuth login locally first and copy token.json to this server."
        )
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    service = build("drive", "v3", credentials=creds)
    return service

# =========================
# UPLOAD FILE
# =========================

def upload_file(local_path, folder_key, filename=None):
    if folder_key not in FOLDERS:
        raise ValueError(f"Folder key '{folder_key}' not found in FOLDERS")
    service = get_service()
    name = filename or os.path.basename(local_path)
    metadata = {"name": name, "parents": [FOLDERS[folder_key]]}
    media = MediaFileUpload(local_path, resumable=True)
    file = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name"
    ).execute()
    print(f"Uploaded: {name} ({file['id']})")
    return file["id"]

# =========================
# DOWNLOAD FILE
# =========================

def download_file(file_id, save_path):
    service = get_service()
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(save_path, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    print(f"Downloaded: {save_path}")

# =========================
# LIST FILES IN FOLDER
# =========================

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

# =========================
# PENDING AUDIO WATCHER
# =========================

def list_pending_recordings():
    service = get_service()
    folder_id = FOLDERS["pending"]
    results = service.files().list(
        q=f'"{folder_id}" in parents and trashed=false',
        fields="files(id, name, createdTime)"
    ).execute()
    return results.get("files", [])

# =========================
# MAKE FILE PUBLIC
# =========================

def make_public_url(file_id):
    service = get_service()
    service.permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"}
    ).execute()
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    print("Public URL created")
    return url

# =========================
# DELETE FILE
# =========================

def delete_file(file_id):
    service = get_service()
    service.files().delete(fileId=file_id).execute()
    print("Deleted:", file_id)

# =========================
# TEST MODE
# =========================

TEST_MODE = False
TEST_FOLDER = "scripts"
TEST_FILENAME = "drive_test.txt"

if __name__ == "__main__" and TEST_MODE:
    print("\n===== DRIVE TEST MODE =====\n")
    try:
        # 1. create test file
        print("Creating test file...")
        with open(TEST_FILENAME, "w") as f:
            f.write(f"Drive connection test\nTime: {datetime.datetime.now()}\n")

        # 2. upload file
        print("Uploading file...")
        file_id = upload_file(TEST_FILENAME, TEST_FOLDER)

        # 3. list files
        print("\nListing files in folder...")
        files = list_files(TEST_FOLDER)
        for file in files[:5]:
            print(f"- {file['name']}")

        # 4. make public
        print("\nCreating public URL...")
        url = make_public_url(file_id)
        print("Public URL:", url)

        print("\n===== TEST COMPLETE =====")

    except Exception as e:
        print("\nERROR:")
        print(e)