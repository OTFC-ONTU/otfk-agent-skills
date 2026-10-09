"""Заливка тем, матеріалів і завдань у Google Classroom з файлу плану (JSON).

  python classroom_sync.py plans/uitp-kg-2026.json                 — dry-run (нічого не змінює)
  python classroom_sync.py plans/uitp-kg-2026.json --apply         — створити в Classroom
  python classroom_sync.py plans/uitp-kg-2026.json --only-files    — лише елементи з файлами
  python classroom_sync.py plans/uitp-kg-2026.json --update --apply — дотягнути вже створені
        елементи до правил (бали, дедлайни, опис, тема) — нічого не видаляє
  python classroom_sync.py plans/uitp-kg-2026.json --check         — перевірка плану за правилами

Правила (докладно — skills/google-classroom-otfk/SKILL.md):
  * maxPoints: 12 балів для 1–2 курсу, 5 балів для 3–4 курсу (plan.course_year);
  * дедлайн для завдань = неділя 23:59 (Київ) тижня «week + due_offset_weeks» (за замовч. +1),
    тобто тиждень на виконання; здача після терміну дозволена (Classroom позначає «Із запізненням»);
  * самостійна робота (СР) без дедлайну, якщо в елементі явно не задано dueDate;
  * теми та елементи створюються у зворотному порядку плану, бо Classroom показує
    нові пости зверху — так сторінка «Завдання» читається зверху вниз як план.

Ідемпотентно: тема або елемент з таким самим заголовком повторно не створюється.
Елемент плану з полем "id": "<courseWorkId>" прив'язується до вже створеного завдання
(напр. старої лабораторної зі зданими роботами): з --update його можна перейменувати,
змінити опис/бали/дедлайн і перенести в іншу тему, НЕ видаляючи здані роботи.
Нічого не видаляє. Без --update нічого не перезаписує.

Матеріали типу {"file": "УІПТ КГ/Лекції 2026/Лекція 1.docx"} (шлях відносно кореня
робочої папки, див. OTFK_ROOT у drive_files.py) завантажуються у Drive-папку курсу (див. drive_files.py) і прикріплюються.
{"folder": "ООП РП/Курсові/Завдання 3РП-11", "pattern": "*.pdf", "name": "…"} – створює
Drive-папку з цими файлами і прикріплює її як один матеріал (напр. індивідуальні завдання).
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from classroom_auth import get_service
from drive_files import DriveUploader

UTC = ZoneInfo("UTC")
POINTS_BY_YEAR = {1: 12, 2: 12, 3: 5, 4: 5}
SR_PREFIX = "самостійна робота"
TITLE_RE = re.compile(
    r"^(Лекція|Практична робота|Лабораторна робота|Самостійна робота|Семінарське заняття|"
    r"Контрольна робота|Курсова робота|Екзамен|Залік|Силабус)\b")


def load_plan(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def default_points(plan):
    year = plan.get("course_year")
    if year is None:
        return None
    return POINTS_BY_YEAR[int(year)]


def resolve_course(svc, plan):
    cid = plan.get("course", {}).get("id")
    if cid:
        return svc.courses().get(id=str(cid)).execute()
    hint = plan.get("course", {}).get("name_hint", "").lower()
    if not hint:
        sys.exit("У плані немає course.id і course.name_hint.")
    found, page = [], None
    while True:
        resp = svc.courses().list(pageSize=100, pageToken=page, teacherId="me").execute()
        found += resp.get("courses", [])
        page = resp.get("nextPageToken")
        if not page:
            break
    match = [c for c in found
             if hint in c["name"].lower() or hint in (c.get("section") or "").lower()]
    if len(match) != 1:
        print("Не вдалося однозначно визначити курс за name_hint =", repr(hint))
        for c in found:
            print(f'  {c["id"]}  {c["name"]}  / {c.get("section","")}')
        sys.exit("Впиши потрібний id у план (course.id).")
    return match[0]


def _paged(call, key, **kw):
    page = None
    while True:
        resp = call(pageToken=page, **kw).execute()
        for x in resp.get(key, []):
            yield x
        page = resp.get("nextPageToken")
        if not page:
            return


def existing_topics(svc, course_id):
    return {t["name"].strip().lower(): t["topicId"]
            for t in _paged(svc.courses().topics().list, "topic", courseId=course_id)}


def existing_items(svc, course_id):
    """title(lower) -> (kind, obj) і також "id:<id>" -> (kind, obj), kind = 'work' | 'material'."""
    out = {}
    # Без courseWorkStates API повертає лише PUBLISHED — чернетки були б невидимі й дублювалися.
    for w in _paged(svc.courses().courseWork().list, "courseWork", courseId=course_id,
                    courseWorkStates=["PUBLISHED", "DRAFT"]):
        out[w["title"].strip().lower()] = ("work", w)
        out["id:" + w["id"]] = ("work", w)
    for w in _paged(svc.courses().courseWorkMaterials().list, "courseWorkMaterial", courseId=course_id,
                    courseWorkMaterialStates=["PUBLISHED", "DRAFT"]):
        out[w["title"].strip().lower()] = ("material", w)
        out["id:" + w["id"]] = ("material", w)
    return out


def is_sr(item):
    return item.get("noDue") is True or item["title"].strip().lower().startswith(SR_PREFIX)


def resolve_date(item, plan):
    """Явна dueDate має пріоритет; СР — без дедлайну; інакше неділя тижня week + offset."""
    if item.get("dueDate"):
        return item["dueDate"]
    if is_sr(item):
        return None
    start = plan.get("semester_start")
    week = item.get("week")
    if not start or not week:
        return None
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d0 = d0 - timedelta(days=d0.weekday())          # понеділок тижня №1
    offset = int(item.get("dueOffsetWeeks", plan.get("due_offset_weeks", 1)))
    weekday = int(item.get("dueWeekday", plan.get("due_weekday", 6)))
    d = d0 + timedelta(days=(int(week) - 1 + offset) * 7 + weekday)
    return d.isoformat()


def due_utc(item, plan, tz):
    """dueDate/dueTime у Classroom — завжди UTC, тому конвертуємо з локального часу."""
    date_s = resolve_date(item, plan)
    if not date_s:
        return None, None
    hhmm = item.get("dueTime", plan.get("due_time", "23:59"))
    local = datetime.strptime(date_s + " " + hhmm, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    u = local.astimezone(UTC)
    return ({"year": u.year, "month": u.month, "day": u.day},
            {"hours": u.hour, "minutes": u.minute})


def item_points(item, plan):
    if item.get("maxPoints") is not None:
        return item["maxPoints"]
    return default_points(plan)


def build_materials(item, uploader=None, apply=False):
    mats = []
    for m in item.get("materials", []):
        if "file" in m:
            if uploader is None:
                continue
            fid = uploader.ensure(m["file"], apply=apply)
            if fid:
                mats.append({"driveFile": {"driveFile": {"id": fid},
                                           "shareMode": m.get("shareMode", "VIEW")}})
        elif "folder" in m:
            if uploader is None:
                continue
            fid = uploader.ensure_folder(m["folder"], m.get("pattern", "*"), m.get("name"), apply=apply)
            mats.append({"driveFile": {"driveFile": {"id": fid},
                                       "shareMode": m.get("shareMode", "VIEW")}})
        elif "link" in m:
            mats.append({"link": {"url": m["link"]}})
        elif "driveFileId" in m:
            mats.append({"driveFile": {"driveFile": {"id": m["driveFileId"]},
                                       "shareMode": m.get("shareMode", "VIEW")}})
        elif "youTubeId" in m:
            mats.append({"youtubeVideo": {"id": m["youTubeId"]}})
    return mats


# ----------------------------------------------------------------------------- check
def check_plan(plan, root_exists):
    problems = []
    if plan.get("course_year") is None:
        problems.append("plan.course_year не задано (1–4) — бали не будуть виставлені за правилом")
    if not plan.get("semester_start"):
        problems.append("plan.semester_start не задано — дедлайни не будуть поставлені")
    pts = default_points(plan)
    for t in plan["topics"]:
        for it in t.get("items", []):
            title = it["title"].strip()
            where = f'«{title}»'
            if not TITLE_RE.match(title):
                problems.append(f'{where}: заголовок не за шаблоном «Тип N. Назва»')
            if not it.get("description", "").strip():
                problems.append(f'{where}: порожній опис')
            if it.get("type", "assignment") != "material":
                p = item_points(it, plan)
                if pts is not None and p != pts:
                    problems.append(f'{where}: maxPoints={p}, а за правилом для {plan["course_year"]} курсу має бути {pts}')
                if is_sr(it):
                    if it.get("dueDate"):
                        problems.append(f'{where}: СР має бути без дедлайну (є dueDate)')
                elif not resolve_date(it, plan):
                    problems.append(f'{where}: немає дедлайну (week або dueDate)')
            for m in it.get("materials", []):
                if "file" in m and not root_exists(m["file"]):
                    problems.append(f'{where}: файл не знайдено або він cloud-only: {m["file"]}')
                if "folder" in m:
                    import glob, os
                    from drive_files import ROOT
                    if not glob.glob(os.path.join(ROOT, m["folder"], m.get("pattern", "*"))):
                        problems.append(f'{where}: у папці немає файлів: {m["folder"]}/{m.get("pattern", "*")}')
    return problems


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--apply", action="store_true", help="реально створювати (без прапорця — dry-run)")
    ap.add_argument("--only-files", action="store_true",
                    help="створювати лише елементи, до яких прикріплено файли (materials.file), і їхні теми")
    ap.add_argument("--update", action="store_true",
                    help="дотягувати вже створені елементи до плану (бали, дедлайн, опис, тема)")
    ap.add_argument("--check", action="store_true", help="лише перевірити план за правилами")
    args = ap.parse_args()

    plan = load_plan(args.plan)
    tz = ZoneInfo(plan.get("timezone", "Europe/Kiev"))

    if args.check:
        import os
        from drive_files import ROOT
        probs = check_plan(plan, lambda rel: os.path.exists(os.path.join(ROOT, rel)) and os.path.getsize(os.path.join(ROOT, rel)) > 0)
        if probs:
            print("Зауваження до плану:")
            for p in probs:
                print("  -", p)
            sys.exit(1)
        print("План відповідає правилам.")
        return

    svc = get_service()
    course = resolve_course(svc, plan)
    cid = course["id"]
    print(f'Курс: {course["name"]} (id={cid})')
    print("РЕЖИМ:", "ЗАПИС У CLASSROOM" if args.apply else "DRY-RUN (нічого не змінюється)")
    pts = default_points(plan)
    print(f'Правила: курс {plan.get("course_year", "?")} → {pts if pts is not None else "бали не задано"} б.; '
          f'дедлайн +{plan.get("due_offset_weeks", 1)} тиждень; СР без дедлайну\n')

    # опис курсу
    want_desc = (plan.get("course") or {}).get("description")
    if want_desc and want_desc.strip() != (course.get("description") or "").strip():
        print("~ опис курсу буде оновлено")
        if args.apply:
            svc.courses().patch(id=cid, updateMask="description",
                                body={"description": want_desc}).execute()

    topics = existing_topics(svc, cid)
    existing = existing_items(svc, cid)
    uploader = DriveUploader(course, plan_path=args.plan)
    created_t = created_i = skipped = updated = 0

    # Зворотний порядок: Classroom показує нові пости зверху.
    for t in reversed(plan["topics"]):
        items = list(t.get("items", []))
        if args.only_files:
            items = [i for i in items if any("file" in m or "folder" in m for m in i.get("materials", []))]
            if not items:
                continue
        tname = t["name"].strip()
        key = tname.lower()
        tid = topics.get(key)
        if tid:
            print(f'= тема вже є: {tname}')
        else:
            print(f'+ тема: {tname}')
            created_t += 1
            if args.apply:
                tid = svc.courses().topics().create(
                    courseId=cid, body={"name": tname}).execute()["topicId"]
                topics[key] = tid

        for item in reversed(items):
            title = item["title"].strip()
            kind = item.get("type", "assignment")
            state = item.get("state", "DRAFT")
            body = {"title": title,
                    "description": item.get("description", ""),
                    "state": state}
            if tid:
                body["topicId"] = tid
            label = "матеріал" if kind == "material" else "завдання"
            d = h = None
            if kind != "material":
                body["workType"] = "ASSIGNMENT" if kind == "assignment" else "SHORT_ANSWER_QUESTION"
                p = item_points(item, plan)
                if p is not None:
                    body["maxPoints"] = p
                d, h = due_utc(item, plan, tz)
                if d:
                    body["dueDate"], body["dueTime"] = d, h

            _d = resolve_date(item, plan) if kind != "material" else None
            due_s = f' (до {_d} {item.get("dueTime", plan.get("due_time", "23:59"))})' if _d else ""
            pts_s = f' [{body["maxPoints"]} б.]' if "maxPoints" in body else ""
            files = [m.get("file") or (m["folder"] + "/" + m.get("pattern", "*"))
                     for m in item.get("materials", []) if "file" in m or "folder" in m]
            files_s = f'  [файли: {", ".join(files)}]' if files else ""

            ekey = "id:" + str(item["id"]) if item.get("id") else title.lower()
            if ekey in existing:
                ekind, ex = existing[ekey]
                if not args.update:
                    print(f'    = вже є: {title}')
                    skipped += 1
                    continue
                # --update: порівняти й дотягнути
                mask = []
                if ex.get("title", "").strip() != title:
                    mask.append("title")
                if ex.get("description", "") != body["description"]:
                    mask.append("description")
                if tid and ex.get("topicId") != tid:
                    mask.append("topicId")
                if ekind == "work":
                    if body.get("maxPoints") is not None and ex.get("maxPoints") != body["maxPoints"]:
                        mask.append("maxPoints")
                    if (ex.get("dueDate"), ex.get("dueTime")) != (d, h):
                        mask += ["dueDate", "dueTime"]
                if not mask:
                    print(f'    = актуально: {title}')
                    skipped += 1
                    continue
                print(f'    ^ оновити ({", ".join(mask)}): {title}{pts_s}{due_s}')
                updated += 1
                if args.apply:
                    patch = {k: body[k] for k in mask if k in body}
                    if "dueDate" in mask and d is None:
                        patch["dueDate"] = None
                        patch["dueTime"] = None
                    api = svc.courses().courseWork() if ekind == "work" else svc.courses().courseWorkMaterials()
                    try:
                        try:
                            api.patch(courseId=cid, id=ex["id"], updateMask=",".join(mask), body=patch).execute()
                        except HttpError as e:
                            if e.resp.status == 400 and b"Due date must be in the future" in e.content:
                                # Минулий дедлайн API не приймає — оновлюємо решту полів, дедлайн лишаємо як є.
                                mask = [k for k in mask if k not in ("dueDate", "dueTime")]
                                patch.pop("dueDate", None); patch.pop("dueTime", None)
                                print(f'      !! дедлайн у минулому, API не приймає — залишено старий; оновлюю: {", ".join(mask) or "нічого"}')
                                if not mask:
                                    updated -= 1
                                    continue
                                api.patch(courseId=cid, id=ex["id"], updateMask=",".join(mask), body=patch).execute()
                            else:
                                raise
                    except HttpError as e:
                        if e.resp.status == 403 and b"ProjectPermissionDenied" in e.content:
                            # Classroom API дозволяє змінювати лише елементи, створені цим самим
                            # OAuth-проєктом; створене вручну у веб-інтерфейсі API не редагує.
                            print(f'      !! НЕ ОНОВЛЕНО (створено вручну, API не має права): {ex.get("title")} '
                                  f'— зміни ({", ".join(mask)}) внести у веб-інтерфейсі')
                            updated -= 1
                            continue
                        raise
                    if "title" in mask:
                        existing[title.lower()] = (ekind, {**ex, **patch})
                continue

            mats = build_materials(item, uploader, apply=args.apply)
            if mats:
                body["materials"] = mats
            api = svc.courses().courseWorkMaterials() if kind == "material" else svc.courses().courseWork()
            print(f'    + {label}: {title}{pts_s}{due_s} — {state}{files_s}')
            created_i += 1
            if args.apply:
                try:
                    api.create(courseId=cid, body=body).execute()
                except HttpError as e:
                    print("      ПОМИЛКА:", e)
                    raise
                existing[title.lower()] = ("material" if kind == "material" else "work", body)
        print()

    # вітальне оголошення
    ann = plan.get("announcement")
    if ann and ann.get("text"):
        first = ann["text"].strip().splitlines()[0].strip().lower()
        have = any(a.get("text", "").strip().splitlines()[:1] and
                   a["text"].strip().splitlines()[0].strip().lower() == first
                   for a in _paged(svc.courses().announcements().list, "announcements", courseId=cid))
        if have:
            print("= оголошення вже є")
        else:
            print(f'+ оголошення: {ann["text"].strip().splitlines()[0]}  — {ann.get("state", "PUBLISHED")}')
            if args.apply:
                svc.courses().announcements().create(
                    courseId=cid, body={"text": ann["text"], "state": ann.get("state", "PUBLISHED")}).execute()

    print(f'\nПідсумок: тем +{created_t}, елементів +{created_i}, оновлено {updated}, без змін {skipped}')
    if not args.apply:
        print("Це був dry-run. Щоб застосувати, додай --apply")


if __name__ == "__main__":
    main()
