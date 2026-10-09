"""Вивантажити НЕПЕРЕВІРЕНІ роботи студентів (TURNED_IN без оцінки) з курсів Classroom.

  python classroom_fetch_subs.py <courseId>=<Скорочення> [<courseId>=<Скор.> ...] --out "<папка>" [--all]

  Приклад: python classroom_fetch_subs.py 877833552126=ООП 884789543028=УІТП --out "../Перевірка 3КГ-11 (2026-09-26)"
  Структура: <out>/<Скор.>/<ЛРn|ПРn|...>/<Прізвище Ім'я>/<файли>; поруч _manifest.json
  (дата здачі, late, файли, посилання, помилки). --all – також вже оцінені роботи.
  Google Docs/Sheets/Slides експортуються в docx/xlsx/pptx; посилання (Canva тощо) – у manifest.links.
"""
import argparse, io, json, os, re, sys, warnings
warnings.filterwarnings("ignore")
from classroom_auth import get_service
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

EXPORT = {
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}
PREFIX = [("Лабораторна", "ЛР"), ("Практична", "ПР"), ("Контрольна", "КР"), ("Семінар", "КР"), ("Самостійна", "СР")]

def allp(fn, key, **kw):
    out, p = [], None
    while True:
        r = fn(pageToken=p, **kw).execute(); out += r.get(key, []); p = r.get("nextPageToken")
        if not p: return out

def safe(s): return re.sub(r'[\\/:*?"<>|]', "_", s).strip()

def work_code(title):
    n = re.search(r"(\d+)", title); n = n.group(1) if n else "?"
    for word, pref in PREFIX:
        if title.lower().startswith(word.lower()): return f"{pref}{n}"
    return safe(title)[:40]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("courses", nargs="+"); ap.add_argument("--out", required=True); ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__)); os.chdir(here)
    svc = get_service()
    drv = build("drive", "v3", credentials=Credentials.from_authorized_user_file("token.json"))
    root = os.path.abspath(a.out); manifest = []
    for spec in a.courses:
        cid, subj = spec.split("=", 1)
        st = {s["userId"]: s["profile"]["name"]["fullName"] for s in allp(svc.courses().students().list, "students", courseId=cid)}
        cw = {w["id"]: w for w in allp(svc.courses().courseWork().list, "courseWork", courseId=cid, courseWorkStates=["PUBLISHED"])}
        subs = allp(svc.courses().courseWork().studentSubmissions().list, "studentSubmissions", courseId=cid, courseWorkId="-", states=["TURNED_IN"])
        for s in subs:
            if s.get("assignedGrade") is not None and not a.all: continue
            w = cw.get(s["courseWorkId"]);
            if not w: continue
            code = work_code(w["title"]); nm = st.get(s["userId"], s["userId"]); parts = nm.split()
            fio = " ".join(parts[::-1]) if len(parts) == 2 else nm
            d = os.path.join(root, subj, code, safe(fio)); os.makedirs(d, exist_ok=True)
            rec = dict(course=cid, subject=subj, work=code, title=w["title"], student=fio, dir=d, late=s.get("late", False),
                       turned_in=[h["stateHistory"]["stateTimestamp"] for h in s.get("submissionHistory", []) if h.get("stateHistory", {}).get("state") == "TURNED_IN"][-1:],
                       files=[], links=[], errors=[])
            for att in s.get("assignmentSubmission", {}).get("attachments", []):
                if "driveFile" in att:
                    fid = att["driveFile"]["id"]
                    try:
                        meta = drv.files().get(fileId=fid, fields="name,mimeType", supportsAllDrives=True).execute()
                        name, mt = safe(meta["name"]), meta["mimeType"]
                        if mt in EXPORT:
                            emt, ext = EXPORT[mt]; req = drv.files().export_media(fileId=fid, mimeType=emt); name += ext
                        elif mt.startswith("application/vnd.google-apps"):
                            rec["links"].append(f"{mt}: {att['driveFile'].get('alternateLink')}"); continue
                        else:
                            req = drv.files().get_media(fileId=fid, supportsAllDrives=True)
                        with io.FileIO(os.path.join(d, name), "wb") as fh:
                            dl = MediaIoBaseDownload(fh, req); done = False
                            while not done: _, done = dl.next_chunk()
                        rec["files"].append(name)
                    except Exception as e:
                        rec["errors"].append(f"{att['driveFile'].get('title')}: {e}"[:300])
                elif "link" in att: rec["links"].append(att["link"]["url"])
                else: rec["links"].append(json.dumps(att, ensure_ascii=False)[:300])
            manifest.append(rec)
            print(f"{subj} {code} {fio}: {rec['files']} {rec['links']} {rec['errors'] or ''}")
    os.makedirs(root, exist_ok=True)
    json.dump(manifest, open(os.path.join(root, "_manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Усього робіт: {len(manifest)}; без файлів (лише посилання): {sum(1 for m in manifest if not m['files'])}")

if __name__ == "__main__":
    main()
