"""Завантаження файлів матеріалів у Google Drive (папка курсу в Classroom).

Ключ кешу — шлях файлу відносно кореня робочої папки (батьківська папка _classroom або OTFK_ROOT).
Кеш: plans/_drive_files.<courseId>.json  { "<шлях>": {"id","size","mtime"} }.
Якщо файл не змінювався — повторно не вантажиться. Якщо змінився — оновлюється
той самий Drive-файл (id зберігається, тож прикріплення в Classroom оновлюються самі).
"""
import json
import os
import sys

from googleapiclient.http import MediaFileUpload

from classroom_auth import get_drive

BASE = os.path.dirname(os.path.abspath(__file__))
# Корінь робочої папки викладача (звідки рахуються шляхи "file" у планах).
# Типово – батьківська папка _classroom; можна перевизначити змінною середовища OTFK_ROOT.
ROOT = os.environ.get("OTFK_ROOT") or os.path.dirname(BASE)
CACHE_DIR = os.path.join(BASE, "plans")

MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
}


def _cache_path(cid):
    return os.path.join(CACHE_DIR, f"_drive_files.{cid}.json")


def _load_cache(cid):
    """Кеш на курс: plans/_drive_files.<courseId>.json (старий спільний файл теж читається)."""
    p = _cache_path(cid)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            return {cid: json.load(fh)}
    old = os.path.join(CACHE_DIR, "_drive_files.json")
    if os.path.exists(old):
        with open(old, encoding="utf-8") as fh:
            return {cid: json.load(fh).get(cid, {})}
    return {cid: {}}


def _save_cache(c, cid):
    with open(_cache_path(cid), "w", encoding="utf-8") as fh:
        json.dump(c[cid], fh, ensure_ascii=False, indent=2)


class DriveUploader:
    def __init__(self, course, plan_path=None):
        self.course = course
        self.cid = course["id"]
        self.folder = (course.get("teacherFolder") or {}).get("id")
        self.cache = _load_cache(self.cid)
        self.cache.setdefault(self.cid, {})
        self._drive = None

    @property
    def drive(self):
        if self._drive is None:
            self._drive = get_drive()
        return self._drive

    def ensure_folder(self, rel_dir, pattern="*", name=None, apply=False):
        """Папка з файлами (напр. індивідуальні завдання): створює Drive-папку в папці курсу,
        завантажує в неї файли rel_dir/pattern і повертає id папки (прикріплюється як один матеріал).
        Кеш: ключ "folder:<rel_dir>"; файли кешуються як звичайні (оновлюються на місці)."""
        import glob
        local_dir = os.path.join(ROOT, rel_dir.replace("\\", "/"))
        files = sorted(glob.glob(os.path.join(local_dir, pattern)))
        if not files:
            sys.exit(f"У папці немає файлів {pattern}: {local_dir}")
        key = "folder:" + rel_dir
        entry = self.cache[self.cid].get(key)
        fid = entry["id"] if entry else None
        if not fid:
            if not apply:
                print(f'        ~ буде створено Drive-папку «{name or os.path.basename(local_dir)}» ({len(files)} файлів {pattern})')
                fid = "DRY-RUN"
            else:
                body = {"name": name or os.path.basename(local_dir),
                        "mimeType": "application/vnd.google-apps.folder"}
                if self.folder:
                    body["parents"] = [self.folder]
                fid = self.drive.files().create(body=body, fields="id", supportsAllDrives=True).execute()["id"]
                self.cache[self.cid][key] = {"id": fid, "name": body["name"]}
                _save_cache(self.cache, self.cid)
                print(f'        ^ створено Drive-папку: {body["name"]}')
        else:
            print(f'        = Drive-папка вже є: {entry.get("name")}')
        for f in files:
            rel = os.path.relpath(f, ROOT).replace(os.sep, "/")
            self.ensure(rel, apply=apply, parent=None if fid == "DRY-RUN" else fid)
        return fid

    def ensure(self, rel_path, apply=False, parent=None):
        """Повертає id Drive-файлу для rel_path. У dry-run нічого не вантажить."""
        local = os.path.join(ROOT, rel_path.replace("\\", "/"))
        if not os.path.exists(local) or os.path.getsize(local) == 0:
            sys.exit(f"Файл не знайдено або він порожній (cloud-only у OneDrive?): {local}")
        st = os.stat(local)
        entry = self.cache[self.cid].get(rel_path)
        fresh = entry and entry.get("size") == st.st_size and int(entry.get("mtime", 0)) == int(st.st_mtime)
        if fresh:
            print(f'        = у Drive вже є: {rel_path}')
            return entry["id"]
        if not apply:
            print(f'        ~ буде завантажено у Drive: {rel_path}' + (" (оновлення)" if entry else ""))
            return entry["id"] if entry else "DRY-RUN"
        ext = os.path.splitext(local)[1].lower()
        media = MediaFileUpload(local, mimetype=MIME.get(ext, "application/octet-stream"), resumable=True)
        name = os.path.basename(local)
        if entry:
            f = self.drive.files().update(fileId=entry["id"], media_body=media,
                                          supportsAllDrives=True).execute()
            print(f'        ^ оновлено у Drive: {rel_path}')
        else:
            body = {"name": name}
            if parent or self.folder:
                body["parents"] = [parent or self.folder]
            f = self.drive.files().create(body=body, media_body=media, fields="id",
                                          supportsAllDrives=True).execute()
            print(f'        ^ завантажено у Drive: {rel_path}')
        self.cache[self.cid][rel_path] = {"id": f["id"], "size": st.st_size,
                                          "mtime": int(st.st_mtime), "name": name}
        _save_cache(self.cache, self.cid)
        return f["id"]
