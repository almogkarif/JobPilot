"""Explicit bounded employer recheck of a report cohort; local files only.

The input database is read-only. This command does not run startup tasks, scans,
rankings or applications. Results can be inspected before applying to a new copy.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_JOBS = 200
MAX_RESPONSE_BYTES = 4_000_000


def load_cohort(database: Path, report: Path):
    report_rows = json.loads(report.read_text())['unclassified_jobs']
    ids = sorted({row['id'] for row in report_rows if any(
        'missing_job_content' in d['reasons'] for d in row['decisions'])})
    if not 1 <= len(ids) <= MAX_JOBS:
        raise ValueError('Expected 1–200 missing-content jobs')
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute('''SELECT j.id,j.title,j.apply_url AS href,
            substr(j.description,1,24000) AS text,j.location,j.external_id,s.identifier
            FROM jobs j JOIN sources s ON s.id=j.source_id
            WHERE j.id IN (''' + ','.join('?' for _ in ids) + ''')
            AND j.canonical_job_id IS NULL AND j.is_active=1 ORDER BY j.id''', ids)]
    if len(rows) != len(ids):
        raise ValueError('Report cohort no longer matches active canonical input')
    return rows


async def recheck(rows):
    from app.collectors.official import PRESETS, _hydrate_detail_rows
    from app.services.track_classification import classify_job
    from types import SimpleNamespace
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['identifier']].append(row)
    results = []
    # Sequential boards; hydration is limited to 8 concurrent detail requests.
    for identifier, group in grouped.items():
        preset = dict(PRESETS[identifier], max_detail_jobs=MAX_JOBS,
                      detail_response_bytes=MAX_RESPONSE_BYTES, require_complete_detail=True)
        checked = await _hydrate_detail_rows(group, preset, retain_unavailable=True)
        by_id = {row['id']: row for row in checked}
        for old in group:
            row = by_id.get(old['id'], old)
            state = row.get('_detail_status', 'incomplete')
            if identifier == 'matrix-israel':
                state = 'category_not_vacancy'
            elif row.get('_detail_complete') and not row.get('_detail_blocked'):
                state = 'recovered'
                row['classification'] = classify_job(SimpleNamespace(
                    title=row['title'], description=row['text'])).to_dict()
            results.append({**row, 'state': state, 'previous_title': old['title'],
                            'previous_length': len(old['text']), 'url': old['href']})
        print(identifier, dict(Counter(r['state'] for r in results if r['identifier']==identifier)), flush=True)
    return results


def write_report(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    labels = {'recovered':'תוכן מלא שוחזר', 'unavailable':'נסגרה או אינה זמינה', 'blocked':'גישה אוטומטית חסומה', 'closed_browser_verified':'סגירה אומתה בדפדפן', 'category_not_vacancy':'דף קטגוריה, לא משרה', 'incomplete':'תוכן טרם פוענח'}
    rows = ''.join('<tr><td>'+str(r['id'])+'</td><td>'+html.escape(r['identifier'])+
        '</td><td><a href="'+html.escape(r['url'],quote=True)+'">'+html.escape(r['title'])+
        '</a></td><td>'+html.escape(labels.get(r['state'],r['state']))+'</td><td>'+str(r['previous_length'])+
        ' → '+str(len(r['text']))+'</td><td>'+html.escape(', '.join(
            d['track'] for d in r.get('classification',{}).get('decisions',[]) if d['status']=='match'))+
        '</td></tr>' for r in result['jobs'])
    path.with_suffix('.html').write_text('<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8">'
        '<title>בדיקה חוזרת של תוכן המשרות</title><style>body{font-family:Arial;margin:32px}td,th{padding:10px;border:1px solid #ddd}table{border-collapse:collapse}pre{direction:ltr}</style>'
        '<h1>בדיקה חוזרת של תוכן המשרות</h1><p>בדיקה מקומית. חסימת גישה אינה הוכחה שמשרה נסגרה.</p><pre>'+
        html.escape(json.dumps({k:v for k,v in result.items() if k!='jobs'},ensure_ascii=False,indent=2))+
        '</pre><table><tr><th>ID</th><th>מקור</th><th>משרה באתר המקור</th><th>תוצאה</th><th>אורך תוכן</th><th>מסלולים</th></tr>'+rows+'</table></html>')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--cohort',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    if args.report.exists() or args.report.with_suffix('.html').exists():
        raise SystemExit('Refusing to overwrite a previous audit; use a new report path')
    rows=load_cohort(args.input,args.cohort)
    checked=asyncio.run(recheck(rows))
    result={'checked_at':datetime.now(timezone.utc).isoformat(), 'input':str(args.input.resolve()),
            'total':len(checked),'counts':dict(Counter(r['state'] for r in checked)), 'jobs':checked}
    write_report(args.report,result)
    print(json.dumps(result['counts']))

if __name__=='__main__':
    main()
