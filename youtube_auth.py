import os
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

CLIENT_SECRET_FILE = "credentials/client_secret.json"
TOKEN_FILE = "credentials/token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]


def connect_youtube():
    credentials = None

    if os.path.exists(TOKEN_FILE):
        credentials = Credentials.from_authorized_user_file(
            TOKEN_FILE, SCOPES
        )

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, SCOPES
            )
            credentials = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(credentials.to_json())

    youtube = build("youtube", "v3", credentials=credentials)

    response = youtube.channels().list(
        part="snippet",
        mine=True
    ).execute()

    channels = response.get("items", [])

    if not channels:
        print("No YouTube channel found.")
        return

    channel = channels[0]["snippet"]

    print("\nYouTube connected successfully!")
    print("Channel:", channel["title"])
    print("Authentication: Successful")


if __name__ == "__main__":
    connect_youtube()