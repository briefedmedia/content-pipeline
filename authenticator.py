from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
import json

SCOPES = ["https://www.googleapis.com/auth/drive"]
CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
creds = flow.run_local_server(port=0)

with open(TOKEN_FILE, "w") as f:
    f.write(creds.to_json())

print("token.json saved! Copy this to your server for headless runs.")