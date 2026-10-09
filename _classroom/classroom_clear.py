"""НЕБЕЗПЕЧНО: видалити ВСЕ зі сторінки «Завдання» курсу (теми, матеріали, завдання).

  python classroom_clear.py <courseId>

Потрібно для перестворення курсу в правильному порядку (напр. на початку семестру).
Просить ввести назву курсу для підтвердження. Оголошення та учнів не чіпає.
Файли у Drive не видаляє (кеш plans/_drive_files.json лишається чинним).
"""
import os
import sys

from classroom_auth import get_service


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cid = sys.argv[1]
    svc = get_service()
    c = svc.courses().get(id=cid).execute()
    works = svc.courses().courseWork().list(courseId=cid, courseWorkStates=["PUBLISHED", "DRAFT"]).execute().get("courseWork", [])
    mats = svc.courses().courseWorkMaterials().list(courseId=cid, courseWorkMaterialStates=["PUBLISHED", "DRAFT"]).execute().get("courseWorkMaterial", [])
    topics = svc.courses().topics().list(courseId=cid).execute().get("topic", [])
    print(f'Курс: {c["name"]} (id={cid})')
    print(f'Буде видалено: завдань {len(works)}, матеріалів {len(mats)}, тем {len(topics)}')
    for w in works:
        print("  [завдання]", w["title"])
    for m in mats:
        print("  [матеріал]", m["title"])
    for t in topics:
        print("  [тема]", t["name"])
    graded = [w["title"] for w in works
              if svc.courses().courseWork().studentSubmissions().list(
                  courseId=cid, courseWorkId=w["id"], states=["TURNED_IN", "RETURNED"]).execute().get("studentSubmissions")]
    if graded:
        sys.exit("СТОП: є здані/оцінені роботи: " + "; ".join(graded))
    confirm = os.environ.get("CLASSROOM_CLEAR_CONFIRM") or input("Введи назву курсу для підтвердження: ")
    if confirm.strip() != c["name"].strip():
        sys.exit("Назва не збігається — нічого не видалено.")
    for w in works:
        svc.courses().courseWork().delete(courseId=cid, id=w["id"]).execute()
    for m in mats:
        svc.courses().courseWorkMaterials().delete(courseId=cid, id=m["id"]).execute()
    for t in topics:
        svc.courses().topics().delete(courseId=cid, id=t["topicId"]).execute()
    print("Готово. Курс порожній.")


if __name__ == "__main__":
    main()
