"""Інвентаризація зданих робіт (лише читання) по всіх активних курсах викладача.

  python review_inventory.py [<папка для _inventory.json>]

Друкує по кожному курсу кількість робіт у стані TURNED_IN і скільки з них без оцінки;
повний знімок (курси, завдання, здачі) пише в <папка>/_inventory.json (типово reviews/<сьогодні>/).
"""
import json, sys, datetime
from pathlib import Path
from classroom_auth import get_service
from classroom_fetch_subs import allp

svc = get_service()
out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / 'reviews' / datetime.date.today().isoformat()
out.mkdir(parents=True, exist_ok=True)
result = []
for c in allp(svc.courses().list, 'courses', teacherId='me', courseStates=['ACTIVE']):
    works = allp(svc.courses().courseWork().list, 'courseWork', courseId=c['id'], courseWorkStates=['PUBLISHED'])
    subs = allp(svc.courses().courseWork().studentSubmissions().list, 'studentSubmissions', courseId=c['id'], courseWorkId='-')
    pending = [s for s in subs if s['state'] == 'TURNED_IN']
    result.append(dict(course=c, works=works, submissions=subs))
    print(c['name'], 'TURNED_IN:', len(pending), 'without grade:', sum(s.get('assignedGrade') is None for s in pending), flush=True)
(out / '_inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print('Записано:', out / '_inventory.json')
