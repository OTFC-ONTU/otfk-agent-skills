"""Ручна авторизація без локального браузера (для VM/сервера/агента).

  python classroom_auth_manual.py url            — друкує посилання для входу
  (відкрити його в будь-якому браузері під робочим акаунтом, дозволити доступ;
   браузер перейде на http://localhost:PORT/?code=... і покаже помилку — це нормально,
   треба скопіювати всю адресу з рядка браузера)
  python classroom_auth_manual.py code "<вставити адресу>"   — обмін коду на token.json
"""
import json
import os
import sys

# redirect_uri = http://localhost — для oauthlib це «небезпечний транспорт», дозволяємо явно
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google_auth_oauthlib.flow import Flow

from classroom_auth import BASE, CREDENTIALS, SCOPES, TOKEN

STATE = os.path.join(os.path.expanduser("~"), ".classroom_auth_state.json")
REDIRECT = "http://localhost:8765/"


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "url"
    if cmd == "url":
        flow = Flow.from_client_secrets_file(CREDENTIALS, SCOPES, redirect_uri=REDIRECT)
        url, state = flow.authorization_url(access_type="offline", prompt="select_account consent",
                                            include_granted_scopes="true")
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump({"state": state, "code_verifier": flow.code_verifier}, fh)
        print(url)
    elif cmd == "code":
        resp = sys.argv[2]
        with open(STATE, encoding="utf-8") as fh:
            st = json.load(fh)
        flow = Flow.from_client_secrets_file(CREDENTIALS, SCOPES, redirect_uri=REDIRECT,
                                             state=st["state"],
                                             code_verifier=st["code_verifier"])
        flow.fetch_token(authorization_response=resp)
        with open(TOKEN, "w", encoding="utf-8") as fh:
            fh.write(flow.credentials.to_json())
        print("OK, token.json оновлено. Scopes:", flow.credentials.scopes)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
