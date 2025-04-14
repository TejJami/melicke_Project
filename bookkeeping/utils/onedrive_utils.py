import os
import requests
from msal import ConfidentialClientApplication

CLIENT_ID = os.getenv("ONEDRIVE_CLIENT_ID")
CLIENT_SECRET = os.getenv("ONEDRIVE_CLIENT_SECRET")
TENANT_ID = os.getenv("ONEDRIVE_TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/.default"]
UPLOAD_FOLDER = "BookkeepingReceipts"  # You can change this

def get_access_token():
    app = ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    result = app.acquire_token_silent(SCOPES, account=None)

    if not result:
        result = app.acquire_token_for_client(scopes=SCOPES)

    if "access_token" in result:
        return result['access_token']
    else:
        raise Exception(f"Failed to obtain token: {result.get('error_description')}")

def upload_to_onedrive(file_obj, file_name):
    access_token = get_access_token()
    upload_url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{UPLOAD_FOLDER}/{file_name}:/content"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/octet-stream"
    }

    response = requests.put(upload_url, headers=headers, data=file_obj.read())

    if response.status_code in [200, 201]:
        return response.json().get('webUrl')  # This is the shareable OneDrive URL
    else:
        raise Exception(f"Upload failed: {response.text}")
