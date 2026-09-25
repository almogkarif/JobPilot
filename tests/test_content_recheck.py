import asyncio
import json
from pathlib import Path
import httpx
import pytest
from app.collectors import official
from app.collectors.microsoft_detail import microsoft_position_detail
from scripts.recheck_missing_content import load_cohort, MAX_JOBS, MAX_RESPONSE_BYTES
from scripts.apply_content_recheck import apply_report

DETAIL='Develop distributed software in Python. Bachelor degree in Computer Science required. '+('Design, test and maintain production services. '*8)


def test_microsoft_position_identity_and_fallback_availability():
    payload={'data':{'id':123,'name':'Engineer','jobDescription':DETAIL,'location':'Israel'},'metadata':{'isFallback':True}}
    assert microsoft_position_detail(payload,'999') is None
    row=microsoft_position_detail(payload,'123')
    assert row['_detail_complete'] and row['_availability_unverified']
    assert row['text']==DETAIL.strip()
    payload['data']['jobDescription']='Apply now'
    assert microsoft_position_detail(payload,'123') is None


@pytest.mark.parametrize('status,expected',[(247,'blocked'),(403,'blocked'),(404,'unavailable'),(503,'http_error')])
def test_recheck_retains_failure_evidence_without_importing_closed_jobs(monkeypatch,status,expected):
    real=httpx.AsyncClient
    monkeypatch.setattr(official.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(status,text='failure')),**kw))
    rows=[dict(id=1,href='https://career.rafael.co.il/job/123/',title='Engineer',text='old')]
    output=asyncio.run(official._hydrate_detail_rows(rows,official.PRESETS['rafael'],retain_unavailable=True))
    assert output[0]['_detail_status']==expected
    assert output[0]['_http_status']==status
    assert output[0]['text']=='old'
    if status==404:
        assert asyncio.run(official._hydrate_detail_rows(rows,official.PRESETS['rafael']))==[]


def test_microsoft_hydration_reads_api_but_does_not_import_fallback(monkeypatch):
    real=httpx.AsyncClient;calls=[]
    def respond(request):
        calls.append(str(request.url))
        if '/api/pcsx/' in request.url.path:
            return httpx.Response(200,json={'data':{'id':123,'name':'Engineer','jobDescription':DETAIL},'metadata':{'isFallback':True}})
        return httpx.Response(200,text='<main>Loading</main>')
    monkeypatch.setattr(official.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(respond),**kw))
    output=asyncio.run(official._hydrate_detail_rows([dict(href='https://apply.careers.microsoft.com/careers/job/123',text='old')],official.PRESETS['microsoft']))
    assert len(calls)==2 and 'position_id=123' in calls[1]
    assert output[0]['_detail_complete'] and output[0]['_detail_blocked']
    assert output[0]['_detail_status']=='availability_unverified'


def test_repair_refuses_existing_output_before_opening_database(tmp_path):
    source=tmp_path/'source.db';source.write_text('untouched')
    output=tmp_path/'output.db';output.write_text('keep')
    with pytest.raises(ValueError,match='new local SQLite'):
        apply_report(source,output,{'jobs':[]})
    assert source.read_text()=='untouched' and output.read_text()=='keep'


def test_copy_repair_preserves_user_state_and_limits_ranking_invalidation(tmp_path):
    import hashlib
    import sqlite3
    import subprocess
    import sys
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import Source,Job,UserJobState,JobRanking,JobSourceIdentity
    source=tmp_path/'source.db';target=tmp_path/'repaired.db'
    engine=create_engine(f'sqlite:///{source}');Base.metadata.create_all(engine)
    with Session(engine) as db:
        s1=Source(name='Mobileye',kind='official_careers',identifier='mobileye')
        s2=Source(name='Mobileye',kind='lever',identifier='eu:mobileye')
        db.add_all([s1,s2]);db.flush()
        old=Job(company='Mobileye',source_id=s1.id,external_id='bb661a53-79b8-459d-a8df-5dd419d62596',title='UUID',description='Apply now',location='Israel',apply_url='https://careers.mobileye.com/jobs/dev/bb661a53-79b8-459d-a8df-5dd419d62596',canonical_key='old')
        live=Job(company='Mobileye',source_id=s2.id,external_id='bb661a53-79b8-459d-a8df-5dd419d62596',title='Engineer',description=DETAIL,location='Israel',apply_url='https://jobs.eu.lever.co/mobileye/bb661a53-79b8-459d-a8df-5dd419d62596',canonical_key='live')
        other=Job(company='Mobileye',source_id=s2.id,external_id='other',apply_url='https://jobs.eu.lever.co/mobileye/other',title='Other',description=DETAIL,location='Israel',canonical_key='other')
        db.add_all([old,live,other]);db.flush()
        db.add_all([UserJobState(job_id=old.id,status='new'),UserJobState(job_id=live.id,status='saved'),JobSourceIdentity(source_id=s1.id,external_id=old.external_id,job_id=old.id),JobRanking(job_id=live.id,stale=False),JobRanking(job_id=other.id,stale=False)])
        db.commit();ids=old.id,live.id,other.id
        report={'input':str(source),'jobs':[dict(id=old.id,url=old.apply_url,identifier='mobileye',state='recovered',title='Software Engineer',text=DETAIL,location='Israel')]}
    with engine.begin() as connection:
        connection.execute(JobRanking.__table__.insert().values(job_id=ids[1],user_id='another-user',stale=False))
    engine.dispose();before=hashlib.sha256(source.read_bytes()).hexdigest()
    path=tmp_path/'report.json';path.write_text(json.dumps(report))
    subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/apply_content_recheck.py'),'--input',str(source),'--output',str(target),'--report',str(path)],check=True,capture_output=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    with sqlite3.connect(target) as db:
        assert db.execute('select canonical_job_id,is_active from jobs where id=?',(ids[0],)).fetchone()==(ids[1],0)
        assert db.execute('select status from user_job_states where job_id=?',(ids[1],)).fetchone()==('saved',)
        assert db.execute('select job_id from job_source_identities').fetchone()==(ids[1],)
        assert dict(db.execute('select job_id,stale from job_rankings'))=={ids[1]:1,ids[2]:0}
        assert db.execute("select stale from job_rankings where user_id='another-user'").fetchone()==(1,)
        assert db.execute('select title from jobs where id=?',(ids[1],)).fetchone()==('Software Engineer',)
        assert not db.execute('pragma foreign_key_check').fetchall()
