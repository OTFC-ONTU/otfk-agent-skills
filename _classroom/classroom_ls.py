"""Показати курси, теми та завдання.

  python classroom_ls.py                 — список курсів (з ID)
  python classroom_ls.py <courseId>      — теми і завдання курсу
"""
import sys

from classroom_auth import get_service


def list_courses(svc):
    page = None
    rows = []
    while True:
        resp = svc.courses().list(pageSize=100, pageToken=page, teacherId="me").execute()
        rows += resp.get("courses", [])
        page = resp.get("nextPageToken")
        if not page:
            break
    if not rows:
        print("Курсів не знайдено (як викладач).")
        return
    for c in rows:
        print(f'{c["id"]:>14}  [{c.get("courseState","?"):8}]  {c["name"]}'
              + (f'  / {c["section"]}' if c.get("section") else ""))


def list_course(svc, course_id):
    c = svc.courses().get(id=course_id).execute()
    print(f'Курс: {c["name"]}  (id={c["id"]}, стан={c.get("courseState")})\n')

    topics = {}
    page = None
    while True:
        resp = svc.courses().topics().list(courseId=course_id, pageToken=page).execute()
        for t in resp.get("topic", []):
            topics[t["topicId"]] = t["name"]
        page = resp.get("nextPageToken")
        if not page:
            break

    items = {}
    for kind, api in (("завдання", svc.courses().courseWork()),
                      ("матеріал", svc.courses().courseWorkMaterials())):
        page = None
        while True:
            key = "courseWork" if kind == "завдання" else "courseWorkMaterial"
            # без фільтра станів API показує лише PUBLISHED
            states = {"courseWorkStates" if kind == "завдання" else "courseWorkMaterialStates":
                      ["PUBLISHED", "DRAFT"]}
            resp = api.list(courseId=course_id, pageToken=page, **states).execute()
            for w in resp.get(key, []):
                items.setdefault(w.get("topicId"), []).append((kind, w))
            page = resp.get("nextPageToken")
            if not page:
                break

    for tid, name in topics.items():
        print(f'# {name}   (topicId={tid})')
        for kind, w in items.get(tid, []):
            due = w.get("dueDate")
            due_s = f' — до {due["year"]}-{due["month"]:02d}-{due["day"]:02d} UTC' if due else ""
            print(f'    [{kind}] {w["title"]}  ({w.get("state")}){due_s}')
        print()
    if None in items:
        print("# (без теми)")
        for kind, w in items[None]:
            print(f'    [{kind}] {w["title"]}  ({w.get("state")})')


if __name__ == "__main__":
    svc = get_service()
    if len(sys.argv) > 1:
        list_course(svc, sys.argv[1])
    else:
        list_courses(svc)
