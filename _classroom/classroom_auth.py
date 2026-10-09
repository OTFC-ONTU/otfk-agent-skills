"""Авторизація в Google Classroom API. Запускається один раз — далі token.json."""
import json
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS = os.path.join(BASE, "credentials.json")
TOKEN = os.path.join(BASE, "token.json")

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses",
    "https://www.googleapis.com/auth/classroom.topics",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials",
    "https://www.googleapis.com/auth/classroom.announcements",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    # Drive: щоб завантажувати файли лекцій/силабусів у Drive курсу і прикріплювати їх
    "https://www.googleapis.com/auth/drive",
]


def get_service():
    creds = None
    if os.path.exists(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
        # якщо в token.json немає якогось із потрібних scope — треба переавторизуватися
        with open(TOKEN, encoding="utf-8") as fh:
            granted = json.load(fh).get("scopes") or []
        if not set(SCOPES) <= set(granted):
            print("token.json видано зі старим набором дозволів — потрібна повторна авторизація.")
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS):
                sys.exit(
                    "Немає credentials.json. Завантаж OAuth-клієнт (Desktop app)\n"
                    "з Google Cloud Console і поклади сюди:\n  " + CREDENTIALS
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    return build("classroom", "v1", credentials=creds)


def get_drive():
    """Drive API з тим самим token.json (потрібен scope drive)."""
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds)


if __name__ == "__main__":
    svc = get_service()
    me = svc.userProfiles().get(userId="me").execute()
    print("OK. Авторизовано як:", me["name"]["fullName"], "<" + me.get("emailAddress", "?") + ">")
