import os
import requests
from msal import ConfidentialClientApplication
from dotenv import load_dotenv
load_dotenv()  

SCOPES = ["https://graph.microsoft.com/.default"]
UPLOAD_FOLDER = "BookkeepingReceipts"

def get_access_token():
    # Load env vars inside the function
    client_id = os.getenv("ONEDRIVE_CLIENT_ID")
    client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")
    tenant_id = os.getenv("ONEDRIVE_TENANT_ID")

    authority = f"https://login.microsoftonline.com/{tenant_id}"

    print("Getting access token...")
    print("CLIENT_ID:", client_id)
    print("TENANT_ID:", tenant_id)
    print("AUTHORITY:", authority)

    app = ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret
    )

    result = app.acquire_token_silent(SCOPES, account=None)

    if not result:
        result = app.acquire_token_for_client(scopes=SCOPES)

    if "access_token" in result:
        print(result) 
        return result['access_token']
    
    else:
        raise Exception(f"Failed to obtain token: {result.get('error_description')}")

def upload_to_onedrive(file_obj, file_name):
    access_token = get_access_token()
    response = requests.get(
                "https://graph.microsoft.com/v1.0/drives",
                headers={"Authorization": f"Bearer {access_token}",
                 "Content-Type": "application/octet-stream"}
            )

    # upload_url = f"https://graph.microsoft.com/v1.0/drives/{get_drive_id()}/root:/{UPLOAD_FOLDER}/{file_name}:/content"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/octet-stream"
    }

    # print("Uploading to:", upload_url)
    # response = requests.put(upload_url, headers=headers, data=file_obj.read())

    if response.status_code in [200, 201]:
        return response.json().get('webUrl')
    else:
        raise Exception(f"Upload failed: {response.text}")
