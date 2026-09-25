"""Explicit canonical migration on a NEW local snapshot; input is opened read-only."""
from __future__ import annotations
import argparse
import html
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    source, target = args.input.resolve(), args.output.resolve()
    if not source.is_file() or target.exists() or source == target:
        raise SystemExit('Input must exist; output must be a NEW local SQLite file')
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
        with sqlite3.connect(target) as preview:
            original.backup(preview)
    os.environ.update(JOBPILOT_DATABASE_URL=f'sqlite:///{target}', JOBPILOT_AUTH_MODE='local',
                      JOBPILOT_STORAGE_MODE='local', JOBPILOT_UNIFIED_CATALOG_PREVIEW='true',
                      JOBPILOT_SCHEDULER_ENABLED='false')
    from app.database import Base, engine, ensure_compatibility_columns
    from app.services.canonical_migration import migrate_local_copy
    Base.metadata.create_all(engine)
    ensure_compatibility_columns()
    report = migrate_local_copy(engine, confirmed_copy=True)
    with sqlite3.connect(target) as preview:
        violations = preview.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            raise RuntimeError(f'Copy failed foreign key verification: {violations[:10]}')
    report.update(input=str(source), preview=str(target))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    headers = '<tr><th>מסלול</th><th>לפני</th><th>אחרי</th><th>נוספו</th><th>הוסרו</th><th>רב־מסלוליות</th></tr>'
    counts = ''.join('<tr><td>'+html.escape(t)+'</td>'+''.join(f'<td>{v[k]}</td>' for k in ('old','new','added','removed','multi_track'))+'</tr>' for t,v in report['per_track'].items())
    unclassified = ''.join('<tr><td>'+str(r['id'])+'</td><td>'+html.escape(r['title'])+'</td><td>'+html.escape('; '.join(d['track']+': '+d['status']+' / '+', '.join(d['reasons']) for d in r['decisions']))+'</td></tr>' for r in report['unclassified_jobs'])
    summary = {k:v for k,v in report.items() if k not in {'changed_jobs','unclassified_jobs','examples'}}
    changes = ''.join('<tr><td>'+str(r['id'])+'</td><td>'+html.escape(r['title'])+'</td><td>'+html.escape(', '.join(r['before']))+'</td><td>'+html.escape(', '.join(r['after']))+'</td></tr>' for r in report['changed_jobs'])
    args.report.with_suffix('.html').write_text('<!doctype html><html dir="rtl" lang="he"><meta charset="utf-8"><title>השוואת קטלוג קנוני</title><style>body{font-family:Arial;margin:30px}td,th{padding:10px;border:1px solid #ddd}table{border-collapse:collapse}</style><h1>קטלוג קנוני — השוואה מקומית בלבד</h1><table>'+headers+counts+'</table><h2>שינויי שיוך</h2><table><tr><th>ID</th><th>משרה</th><th>לפני</th><th>אחרי</th></tr>'+changes+'</table><h2>משרות ללא שיוך</h2><p>כולל משרות שהוחרגו לפי הכללים ומקרים שדורשים בדיקה; לא כולן שגיאות.</p><table><tr><th>ID</th><th>משרה</th><th>נימוקים</th></tr>'+unclassified+'</table><h2>נתוני מיגרציה מלאים</h2><pre dir="ltr">'+html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></html>',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'changed_jobs','unclassified_jobs','examples'}},ensure_ascii=False))


if __name__ == '__main__':
    main()
