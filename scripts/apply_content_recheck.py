"""Apply a reviewed content audit to a NEW local canonical copy only."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def apply_report(source, target, report):
    source,target=Path(source).resolve(),Path(target).resolve()
    if not source.is_file() or target.exists() or source==target:
        raise ValueError('Input must exist and output must be a new local SQLite copy')
    if Path(report['input']).resolve()!=source or not 1<=len(report['jobs'])<=200:
        raise ValueError('Audit must match this input and contain at most 200 jobs')
    if len({r['id'] for r in report['jobs']})!=len(report['jobs']):
        raise ValueError('Duplicate audit IDs')
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as original:
        for row in report['jobs']:
            actual=original.execute('SELECT apply_url FROM jobs WHERE id=? AND canonical_job_id IS NULL',(row['id'],)).fetchone()
            if not actual or actual[0]!=row['url']:
                raise ValueError('Audit URL no longer matches input')
        with sqlite3.connect(target) as copy:
            original.backup(copy)
    os.environ.update(JOBPILOT_DATABASE_URL=f'sqlite:///{target}',JOBPILOT_AUTH_MODE='local',
                      JOBPILOT_STORAGE_MODE='local',JOBPILOT_UNIFIED_CATALOG_PREVIEW='true',
                      JOBPILOT_SCHEDULER_ENABLED='false')
    from sqlalchemy import create_engine, select, update, delete, text, func
    from sqlalchemy.orm import Session
    from app.models import Job, Source, JobRanking, JobTrack, JobSourceIdentity, UserJobState, Application, OpenAnswerDraft
    from app.services.unified_catalog import replace_job_tracks
    from app.services.track_classification import classify_job
    from app.services.ranking.service import job_fingerprint
    from app.services.matching import extract_experience, extract_skills
    from app.services.degree_requirements import extract_degree_requirement_details
    from app.utils import dumps
    engine=create_engine(f'sqlite:///{target}')
    counts=Counter()
    now=datetime.now(timezone.utc)
    with Session(engine) as db, db.begin():
        for row in report['jobs']:
            job=db.get(Job,row['id'])
            if row['state'] in {'unavailable','closed_browser_verified','category_not_vacancy'}:
                job.is_active=False;job.removed_at=now
                db.execute(delete(JobTrack).where(JobTrack.job_id==job.id))
                db.execute(update(JobSourceIdentity).where(JobSourceIdentity.job_id==job.id).values(is_active=False))
                counts['deactivated']+=1
                continue
            if row['state']!='recovered':
                counts['preserved_unresolved']+=1
                continue
            # Exact UUID in the known Mobileye/Lever pair, never title similarity.
            duplicate=None
            if row['identifier']=='mobileye':
                UUID(job.external_id)  # Reject non-UUID identities before cross-provider aliasing.
                duplicate=db.scalar(select(Job).join(Source,Job.source_id==Source.id).where(
                    Source.kind=='lever',Source.identifier=='eu:mobileye',
                    Job.external_id==job.external_id,Job.canonical_job_id.is_(None),Job.id!=job.id))
            if duplicate:
                # This repair only merges untouched legacy placeholders. Anything
                # with user actions requires the dedicated state migration instead.
                connection=db.connection()
                states=UserJobState.__table__
                acted=connection.scalar(select(states.c.id).where(states.c.job_id==job.id,states.c.status!='new').limit(1))
                apps,drafts=Application.__table__,OpenAnswerDraft.__table__
                if acted or connection.scalar(select(apps.c.id).where(apps.c.job_id==job.id).limit(1)) or connection.scalar(select(drafts.c.id).where(drafts.c.job_id==job.id).limit(1)):
                    raise ValueError('Placeholder has user activity; use explicit state migration')
                for state in connection.execute(select(states.c.id,states.c.user_id).where(states.c.job_id==job.id)).mappings().all():
                    existing=connection.scalar(select(states.c.id).where(states.c.job_id==duplicate.id,states.c.user_id==state['user_id']))
                    if not existing:
                        connection.execute(states.update().where(states.c.id==state['id']).values(job_id=duplicate.id))
                    # Conflicting untouched state stays on the retained alias;
                    # the existing canonical user state always wins.
                db.execute(update(JobSourceIdentity).where(JobSourceIdentity.job_id==job.id).values(job_id=duplicate.id,is_active=True))
                db.execute(delete(JobTrack).where(JobTrack.job_id==job.id))
                job.canonical_job_id=duplicate.id;job.canonical_key=None;job.is_active=False
                row['canonical_id']=duplicate.id
                counts['duplicate_aliases']+=1
                job=duplicate
            job.title=row['title'];job.description=row['text']
            if row.get('location'):job.location=row['location']
            content=job.title+'\n'+job.description
            job.skills_json=dumps(extract_skills(content))
            job.experience_min,job.experience_max=extract_experience(content)
            degree=extract_degree_requirement_details(content)
            job.degree_requirement,job.degree_required=degree.level,degree.required
            job.degree_experience_alternative=degree.experience_alternative
            job.source_fingerprint=job_fingerprint(job)
            job.updated_at=now;job.is_active=True;job.removed_at=None
            replace_job_tracks(db,job,classify_job(job))
            db.connection().execute(JobRanking.__table__.update().where(JobRanking.job_id==job.id).values(stale=True))
            counts['content_updated']+=1
        db.flush()
        if db.execute(text('PRAGMA foreign_key_check')).all():
            raise ValueError('Foreign key validation failed')
        counts['active_canonical']=db.scalar(select(func.count(Job.id)).where(Job.is_active.is_(True),Job.canonical_job_id.is_(None)))
    engine.dispose()
    return dict(counts)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();report=json.loads(args.report.read_text())
    result=apply_report(args.input,args.output,report)
    result.update(output=str(args.output.resolve()))
    args.output.with_suffix('.recheck.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result))
