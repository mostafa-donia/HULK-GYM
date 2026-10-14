from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/contacts']
DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)
TOKEN_PATH = DATA_DIR / 'token.json'
CREDENTIALS_PATH = DATA_DIR / 'credentials.json'

# Load existing token or login
if TOKEN_PATH.exists():
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
else:
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_PATH),
        SCOPES
    )
    creds = flow.run_local_server(port=0)

    with open(TOKEN_PATH, "w", encoding="utf-8") as token:
        token.write(creds.to_json())

# Build the People API service
service = build("people", "v1", credentials=creds)

# Contact information
contact = {
    "names": [
        {
            "givenName": "ahmed abd elhadi python"
        }
    ],
    "phoneNumbers": [
        {
            "value": "+201029375779"
        }
    ]
}

# Create contact
result = service.people().createContact(body=contact).execute()

print("Contact created!")
print(result["resourceName"])

