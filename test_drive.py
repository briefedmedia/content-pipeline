from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_ID = "1ZuCmxYRmYQwbMoMTIIqntvc0zMAd6aqa"

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build("drive", "v3", credentials=creds)

print("Test 1: Listing all files the service account can see...")
results = service.files().list(fields="files(id, name)").execute()
files = results.get("files", [])
if files:
    for f in files:
        print(f"  Found: {f['name']} ({f['id']})")
else:
    print("  No files found -- service account can't see anything in Drive")

print(f"\nTest 2: Looking for folder {FOLDER_ID} directly...")
try:
    folder = service.files().get(fileId=FOLDER_ID, fields="id,name").execute()
    print(f"  Found folder: {folder['name']}")
except Exception as e:
    print(f"  Cannot access folder: {e}")