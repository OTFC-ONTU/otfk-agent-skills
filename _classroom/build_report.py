"""Збирає HTML-звіт перевірки робіт (пошук за ПІБ, фільтри група/предмет/робота, вкладка «Підозри»).

  python build_report.py --results results.json --manifest "<Перевірка…>/_manifest.json" \
      --reviews "<Перевірка…>" [--prev prev_grades.json] [--susp susp.json] \
      [--max 5|12] --title "Перевірка робіт Classroom" --out "<Перевірка…>/Перевірка <група> (<дата>).html"

results.json – масив об'єктів (один на роботу):
  number (номер у маніфесті, з 1), subject (= назва папки предмета під --reviews, напр. "ООП 3КГ-11" або "ООП"),
  group (необов'язково, якщо групи немає в subject), work ("ЛР3"),
  student, claimed_level, actual_level, grade, alt_grade, confidence, tasks, ai_signs, plagiarism,
  manipulation, comment_student, teacher_notes, not_checked
prev_grades.json – {"номер": оцінка} попередньої перевірки (необов'язково; без нього колонка «Попер.» порожня).
susp.json – масив [тип, [студенти], предмет, робота, що саме, сила]; тип «Сліди ШІ» / «Маніпуляція» / інше = збіги.
Повний відгук береться з <reviews>/<subject>/<work>/<student>/Відгук.md (якщо є).
Посилання «Файли роботи» – відносні: HTML має лежати в корені папки перевірки (поруч із папками предметів).
Шаблон – report_template.html поруч зі скриптом. Потрібно: pip install markdown
"""
import argparse, json, os
from datetime import datetime, timezone, timedelta
import markdown

ap = argparse.ArgumentParser()
ap.add_argument('--results', required=True); ap.add_argument('--manifest', required=True)
ap.add_argument('--reviews', required=True); ap.add_argument('--prev'); ap.add_argument('--susp')
ap.add_argument('--title', default='Перевірка робіт Classroom'); ap.add_argument('--subtitle', default='')
ap.add_argument('--note', default=''); ap.add_argument('--max', type=int, default=5, choices=[5, 12]); ap.add_argument('--out', required=True)
a = ap.parse_args()

man = json.load(open(a.manifest, encoding='utf-8'))
res = {r['number']: r for r in json.load(open(a.results, encoding='utf-8'))}
prev = {int(k): v for k, v in json.load(open(a.prev, encoding='utf-8')).items()} if a.prev else {}
SUSP = json.load(open(a.susp, encoding='utf-8')) if a.susp else []
kyiv = timezone(timedelta(hours=3))

rows = []
for n, m in enumerate(man, 1):
    r = res.get(n) or {'number': n, 'subject': m['subject'], 'work': m['work'], 'student': m['student'],
                       'actual_level': 'не перевірено', 'grade': None, 'not_checked': 'вся робота'}
    subj, _, grp = r['subject'].partition(' ')
    grp = r.get('group') or grp
    t = m['turned_in'][-1] if m.get('turned_in') else ''
    if t:
        t = datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(kyiv).strftime('%d.%m %H:%M')
    md = os.path.join(a.reviews, r['subject'], r['work'], r['student'], 'Відгук.md')
    full = markdown.markdown(open(md, encoding='utf-8').read(), extensions=['tables']) if os.path.exists(md) else ''
    def insusp(pred):
        return any(r['student'] in s[1] and s[2] == subj and r['work'] in s[3] and pred(s[0]) for s in SUSP)
    flags = []
    if insusp(lambda ty: ty not in ('Сліди ШІ', 'Маніпуляція')): flags.append('plag')
    if insusp(lambda ty: ty == 'Сліди ШІ') or 'сильн' in (r.get('ai_signs') or '').lower(): flags.append('ai')
    if r.get('manipulation') or insusp(lambda ty: ty == 'Маніпуляція'): flags.append('manip')
    rows.append(dict(n=n, subj=subj, grp=grp or '—', work=r['work'], st=r['student'], at=t, late=bool(m.get('late')),
                     claimed=r.get('claimed_level') or '', actual=r.get('actual_level') or '', prev=prev.get(n),
                     g=r.get('grade'), alt=r.get('alt_grade'), conf=r.get('confidence') or '', tasks=r.get('tasks') or '',
                     ai=r.get('ai_signs') or '', plag=r.get('plagiarism') or '', manip=r.get('manipulation') or '',
                     comment=r.get('comment_student') or '', notes=r.get('teacher_notes') or '',
                     nc=r.get('not_checked') or '', full=full, flags=flags,
                     files=[f"{r['subject']}/{r['work']}/{r['student']}/{f}" for f in m.get('files', [])]))

susp = [dict(type=s[0], who=s[1], subj=s[2], work=s[3], what=s[4], power=s[5]) for s in SUSP]
meta = dict(max=a.max, title=a.title, subtitle=a.subtitle, note=a.note, hasPrev=bool(prev),
            key='otfk-review-' + os.path.splitext(os.path.basename(a.out))[0])
data = json.dumps({'rows': rows, 'susp': susp, 'meta': meta}, ensure_ascii=False).replace('</', '<\\/')
tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'report_template.html'), encoding='utf-8').read()
open(a.out, 'w', encoding='utf-8').write(tpl.replace('/*__DATA__*/null', data))
print('OK', a.out, len(rows), 'робіт')
