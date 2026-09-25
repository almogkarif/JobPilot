"""Explicit, versioned SQLite-copy consolidation. Never called during startup."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from types import SimpleNamespace

from sqlalchemy import DateTime, MetaData, bindparam, text

from ..models import JobRanking, ApplicationEvent, UserJobState
from .track_classification import classify_job, TRACKS
from .unified_catalog import canonical_job_key, source_identity
from .location_filter import is_israel_location
from .job_cleanup import SUBMITTED_APPLICATION_STATUSES
from .ranking.service import job_fingerprint_values

VERSION = 'canonical-local-v1'
BATCH_SIZE = 100


def migrate_local_copy(engine, *, confirmed_copy=False):
    if not confirmed_copy or engine.dialect.name != 'sqlite':
        raise RuntimeError('Migration requires an explicitly confirmed local SQLite copy')
    with engine.begin() as c:
        return _migrate_catalog(c)


def _migrate_catalog(c, *, version=VERSION, catalog_owner=None):
    """Shared consolidation; callers own copy validation, bounds and transaction."""
    postgres = c.dialect.name == 'postgresql'
    def rows(sql, params=None):
        return [dict(r) for r in c.execute(text(sql), params or {}).mappings()]
    def pages(table, columns='*', where='1=1', params=None):
        last_id = None
        while True:
            page = rows(f'SELECT {columns} FROM {table} WHERE ({where}) '
                        + ('AND id>:last_id ' if last_id is not None else '')
                        + 'ORDER BY id LIMIT :limit', dict(params or {}, last_id=last_id, limit=BATCH_SIZE))
            if not page:
                return
            yield from page
            last_id = page[-1]['id']

    # Textual SQL deliberately preserves legacy fields/defaults exactly. Bind
    # datetime values explicitly rather than relying on sqlite3's deprecated
    # implicit datetime adapter. Unmodified SQLite snapshot strings stay strings.
    def statement(sql, params):
        dates = {key for row in params for key, value in row.items()
                 if isinstance(value, datetime)}
        return text(sql).bindparams(*(bindparam(key, type_=DateTime(timezone=True)) for key in dates))

    pending = defaultdict(list)
    def flush(sql=None):
        for query in ([sql] if sql is not None else list(pending)):
            batch = pending.pop(query, [])
            if batch:
                c.execute(statement(query, batch), batch)
    def enqueue(sql, params):
        pending[sql].append(params)
        if len(pending[sql]) >= BATCH_SIZE:
            flush(sql)
    done = rows("SELECT snapshot_json FROM catalog_migration_archive WHERE entity_table='__migration__' AND entity_id=1")
    if done:
        return {**json.loads(done[0]['snapshot_json']), 'already_migrated': True}
    catalog_where = 'user_id=:catalog_owner' if catalog_owner is not None else '1=1'
    catalog_params = {'catalog_owner': catalog_owner} if catalog_owner is not None else {}
    sources = rows(f'SELECT * FROM sources WHERE {catalog_where} ORDER BY id LIMIT 2001', catalog_params)
    jobs = rows('SELECT id,source_id,external_id,career_track,apply_url,is_active FROM jobs '
                f'WHERE {catalog_where} ORDER BY id LIMIT 50001', catalog_params)
    if len(sources) > 2000 or len(jobs) > 50000:
        raise RuntimeError('Local migration bound exceeded; no partial consolidation is allowed')
    report = {'version': version, 'sources_before': len(sources), 'jobs_before': len(jobs),
              'per_track': {t: dict(old=0,old_rows=0,new=0,added=0,removed=0,multi_track=0,changed=0,duplicate_rows=0,consolidated_rows=0,unclassified=0,application_migrations=0,state_migrations=0) for t in TRACKS},
              'source_aliases': 0, 'job_aliases': 0, 'application_migrations': 0,
              'application_conflicts': 0, 'state_migrations': 0, 'state_conflicts': 0, 'states_created': 0,
              'unclassified': 0, 'unmapped_state': [], 'changed_jobs': [], 'unclassified_jobs': [], 'examples': []}
    def archive(table, row, canonical_id):
        enqueue('INSERT INTO catalog_migration_archive '
            '(entity_table,entity_id,canonical_id,snapshot_json,migration_version) VALUES (:t,:i,:c,:s,:v) ON CONFLICT(entity_table,entity_id) DO NOTHING',
            dict(t=table,i=row['id'],c=canonical_id,s=json.dumps(row,ensure_ascii=False,default=str),v=version))
    source_groups = defaultdict(list)
    source_by_id = {s['id']:s for s in sources}
    for source in sources:
        source_groups[(source['kind'].strip().lower(),source['identifier'].strip().lower())].append(source)
    source_map = {}
    source_updates = []
    for key, group in source_groups.items():
        canonical = min(group, key=lambda s:(bool(json.loads(s['metadata_json'] or '{}').get('retired') or json.loads(s['metadata_json'] or '{}').get('duplicate_of')), s['id']))
        enabled = any(s['enabled'] and not json.loads(s['metadata_json'] or '{}').get('retired') for s in group)
        for source in group:
            source_map[source['id']] = canonical['id']
            archive('sources', source, canonical['id'])
            if source['id'] != canonical['id']:
                enqueue('UPDATE sources SET canonical_source_id=:canonical, enabled=FALSE, identity_key=NULL WHERE id=:id',
                          dict(canonical=canonical['id'],id=source['id']))
                report['source_aliases'] += 1
        source_updates.append(dict(key=source_identity(*key), enabled=enabled,id=canonical['id']))
    # Release any existing alias identity slots before filling canonical slots.
    flush()
    for update in source_updates:
        enqueue("UPDATE sources SET career_track='shared', identity_key=:key, enabled=:enabled WHERE id=:id", update)
    flush()
    # Union exact board IDs and exact posting URLs; no title-only guesses.
    parent = {j['id']:j['id'] for j in jobs}
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    identities = {}
    for j in jobs:
        s = source_by_id[j['source_id']]
        keys = [('board',source_map[s['id']],j['external_id']),
                ('posting',canonical_job_key(s['kind'],s['identifier'],j['external_id'],j['apply_url']))]
        for key in keys:
            if key in identities:
                parent[find(j['id'])] = find(identities[key])
            identities[key] = j['id']
    groups = defaultdict(list)
    for j in jobs: groups[find(j['id'])].append(j)
    job_map, old_tracks = {}, {}
    for group in groups.values():
        # Prefer an existing row on its canonical source to avoid violating old identities.
        canonical = min(group,key=lambda j:(j['source_id'] != source_map[j['source_id']],j['id']))
        for j in group:
            job_map[j['id']] = canonical['id']; old_tracks[j['id']] = j['career_track']
    # Refuse ambiguous in-flight workers rather than duplicate/resubmit them.
    applications = list(pages('applications'))
    app_groups = defaultdict(list)
    for a in applications:
        if a['job_id'] not in job_map:
            report['unmapped_state'].append({'table':'applications','id':a['id']})
            continue
        app_groups[(a['user_id'],job_map[a['job_id']])].append(a)
    for group in app_groups.values():
        if len(group)>1 and any(a['status']=='applying' for a in group):
            raise RuntimeError(f"Consolidation requires idle workers for applications {[a['id'] for a in group]}")
    app_winners = {}
    verified_attempts = {}
    for attempt in pages('application_attempts', 'id,application_id,finished_at,started_at',
                         "verification_state='verified'"):
        verified_attempts[attempt['application_id']] = attempt
    for (uid,jid), group in app_groups.items():
        verified = verified_attempts.keys()
        def priority(a):
            submitted = bool(a['submitted_at']) or a['status'] in SUBMITTED_APPLICATION_STATUSES or a['id'] in verified
            return (not submitted, a['job_id'] != jid, a['id'])
        evidence = min(group,key=priority)
        # Keep the existing canonical unique slot; merge submission evidence into it.
        # Every original row is archived before any fields or children change.
        keeper = next((a for a in group if a['job_id']==jid), evidence)
        merged = dict(evidence)
        merged.update(id=keeper['id'],job_id=jid,canonical_application_id=None,
                      originating_track=evidence.get('originating_track') or old_tracks[evidence['job_id']])
        if evidence['id'] in verified and merged['status'] not in SUBMITTED_APPLICATION_STATUSES:
            merged['status'] = 'submitted'
            receipt = verified_attempts[evidence['id']]
            merged['submitted_at'] = merged['submitted_at'] or receipt['finished_at'] or receipt['started_at']
        app_winners[(uid,jid)] = merged
        for a in group:
            archive('applications',a,keeper['id'])
            origin = a.get('originating_track') or old_tracks[a['job_id']]
            c.execute(text('UPDATE applications SET originating_track=:t WHERE id=:id'),dict(t=origin,id=a['id']))
            if a['id'] == keeper['id']: continue
            c.execute(text('UPDATE applications SET canonical_application_id=:winner WHERE id=:id'),dict(winner=keeper['id'],id=a['id']))
            for table in ('application_attempts','application_events','blockers'):
                for child in rows(f'SELECT * FROM {table} WHERE application_id=:id',dict(id=a['id'])):
                    archive(table,child,keeper['id'])
                c.execute(text(f'UPDATE {table} SET application_id=:winner WHERE application_id=:id'),dict(winner=keeper['id'],id=a['id']))
            report['application_conflicts'] += 1
        c.execute(statement('UPDATE applications SET '+','.join(f'{k}=:{k}' for k in merged if k not in {'id','user_id'})+' WHERE id=:id', [merged]),merged)
        report['application_migrations'] += sum(a['job_id']!=jid for a in group)
        for a in group:
            if a['job_id']!=jid and old_tracks[a['job_id']] in TRACKS:
                report['per_track'][old_tracks[a['job_id']]]['application_migrations'] += 1
        if len(group)>1:
            c.execute(ApplicationEvent.__table__.insert().values(application_id=keeper['id'], user_id=uid,
                event_type='canonical_consolidation', to_status=merged['status'],
                message='Historical applications consolidated; original records retained in the migration archive.',
                details_json=json.dumps({'original_applications': [{'id':a['id'],'status':a['status'],
                    'job_id':a['job_id'],'submitted_at':a['submitted_at'],'notes':a['notes']} for a in group]},default=str)))
        if merged['submitted_at'] or merged['status'] in SUBMITTED_APPLICATION_STATUSES:
            for blocker in rows("SELECT * FROM blockers WHERE application_id=:id AND status='open'",dict(id=keeper['id'])):
                archive('blockers',blocker,keeper['id'])
            params = dict(id=keeper['id'],now=datetime.now(timezone.utc))
            c.execute(statement("UPDATE blockers SET status='resolved',resolved_at=:now WHERE application_id=:id AND status='open'", [params]), params)

    # Active classification is compared on unique physical vacancies per track.
    # The projected index above enforces the 50,000-row ceiling; full payloads
    # are fetched once in bounded pages, including aliases spanning page edges.
    full_jobs = {job['id']: job for job in pages('jobs', where=catalog_where, params=catalog_params)}
    for job in full_jobs.values():
        if job_map[job['id']] != job['id']:
            enqueue('UPDATE jobs SET canonical_job_id=:jid,is_active=FALSE,canonical_key=NULL WHERE id=:id',
                    dict(jid=job_map[job['id']],id=job['id']))
    flush()
    for group in groups.values():
        jid = job_map[group[0]['id']]
        full = [full_jobs[j['id']] for j in group]
        canonical = next(j for j in full if j['id']==jid)
        payload = max(full,key=lambda j:(bool(j['is_active']),len(j['description'] or ''),str(j['updated_at'] or '')))
        before = {j['career_track'] for j in full if j['is_active'] and j['career_track'] in TRACKS}
        active = any(j['is_active'] for j in full)
        classification = classify_job(SimpleNamespace(title=payload['title'],description=payload['description']))
        matched = set(classification.matched_tracks) if is_israel_location(payload['location']) else set()
        after = matched if active else set()
        for track in TRACKS:
            stat = report['per_track'][track]
            old_rows = sum(j['is_active'] and j['career_track']==track for j in full)
            stat['old_rows'] += old_rows
            stat['duplicate_rows'] += max(0,old_rows-1)
            stat['consolidated_rows'] += sum(j['id']!=jid and j['career_track']==track for j in full)
            stat['unclassified'] += track in before and not after
            stat['old'] += track in before; stat['new'] += track in after
            stat['added'] += track in after-before; stat['removed'] += track in before-after
            stat['multi_track'] += track in after and len(after)>1
            stat['changed'] += before != after and track in before|after
        report['unclassified'] += active and not matched
        if active and not matched:
            report['unclassified_jobs'].append(dict(id=jid,title=payload['title'],url=payload['apply_url'],decisions=classification.to_dict()['decisions']))
        if active and before != after:
            report['changed_jobs'].append(dict(id=jid,title=payload['title'],before=sorted(before),after=sorted(after)))
        if active and len(after)>1 and len(report['examples'])<12:
            report['examples'].append(dict(id=jid,title=payload['title'],url=payload['apply_url'],tracks=sorted(after)))
        for j in full:
            archive('jobs',j,jid)
            if j['id']!=jid:
                report['job_aliases'] += 1
            key = (source_map[j['source_id']],j['external_id'])
            enqueue('INSERT INTO job_source_identities(source_id,external_id,job_id,is_active,last_seen_at,user_id) '
                'VALUES (:sid,:ext,:jid,:active,:now,:uid) ON CONFLICT(source_id,external_id) DO UPDATE SET is_active=' +
                ('job_source_identities.is_active OR excluded.is_active' if postgres else 'max(is_active,excluded.is_active)'),
                dict(sid=key[0],ext=key[1],jid=jid,active=j['is_active'],now=datetime.now(timezone.utc),uid=j['user_id']))
        source = source_by_id[canonical['source_id']]
        fields = {k:payload[k] for k in ('title','company','location','workplace','description','apply_url','source_url','published_at','skills_json','experience_min','experience_max','degree_requirement','degree_required','degree_experience_alternative')}
        # The migration always produces canonical fingerprints, even before the
        # runtime preview flag is enabled. SQLite strips timezone metadata.
        published = fields['published_at']
        if isinstance(published, str):
            published = datetime.fromisoformat(published)
        if isinstance(published, datetime):
            published = (published.replace(tzinfo=timezone.utc) if published.tzinfo is None
                         else published.astimezone(timezone.utc))
        fields.update(id=jid,source_id=source_map[canonical['source_id']],is_active=active,
            canonical_key=canonical_job_key(source['kind'],source['identifier'],canonical['external_id'],payload['apply_url']),
            classification_json=json.dumps(classification.to_dict(),ensure_ascii=False),
            source_fingerprint=job_fingerprint_values('shared',payload['title'],payload['description'],payload['location'],payload['workplace'],published))
        enqueue('UPDATE jobs SET '+','.join(f'{k}=:{k}' for k in fields if k!='id')+' WHERE id=:id',fields)
        for track in matched:
            decision = next(d for d in classification.decisions if d.track==track)
            enqueue('INSERT INTO job_tracks(job_id,career_track,classifier_version,reason,user_id) VALUES(:id,:t,:v,:r,:u) ON CONFLICT(job_id,career_track) DO NOTHING',
                      dict(id=jid,t=track,v=classification.version,r=json.dumps(decision.reasons),u=canonical['user_id']))
    flush()
    states = defaultdict(list)
    for row in pages('user_job_states'):
        states[(row['user_id'],job_map[row['job_id']])].append(row)
    weights = {'submitted':100,'interview':100,'offer':100,'hidden':90,'saved':80,'queued':70,'applying':70,'skipped':60,'new':0}
    for (uid,jid), group in states.items():
        keeper = next((r for r in group if r['job_id']==jid),group[0])
        chosen = max(group,key=lambda r:(weights.get(r['status'],50),str(r['updated_at'] or '')))
        for row in group: archive('user_job_states',row,keeper['id'])
        status = chosen['status']
        app = app_winners.get((uid,jid))
        if status != 'hidden' and app and (app['submitted_at'] or app['status'] in {'submitted','interview','offer'}): status=app['status']
        enqueue('UPDATE user_job_states SET job_id=:jid,status=:s WHERE id=:id',dict(jid=jid,s=status,id=keeper['id']))
        report['state_migrations'] += sum(r['job_id']!=jid for r in group)
        report['state_conflicts'] += max(0,len(group)-1)
        for row in group:
            if row['job_id']!=jid and old_tracks[row['job_id']] in TRACKS:
                report['per_track'][old_tracks[row['job_id']]]['state_migrations'] += 1
    for (uid,jid), application in app_winners.items():
        if (uid,jid) not in states:
            c.execute(UserJobState.__table__.insert().values(user_id=uid,job_id=jid,status=application['status']))
            report['states_created'] += 1
    for row in pages('open_answer_drafts'):
        if row['job_id']!=job_map[row['job_id']]:
            archive('open_answer_drafts',row,job_map[row['job_id']])
            enqueue('UPDATE open_answer_drafts SET job_id=:jid WHERE id=:id',dict(jid=job_map[row['job_id']],id=row['id']))
    for row in pages('campaign_runs', where='activated_at IS NULL'):
        archive('campaign_runs',row,row['id'])
        enqueue("UPDATE campaign_runs SET preview_token_hash='',preview_expires_at=NULL WHERE id=:id",dict(id=row['id']))
    flush()
    # Keep the complete old ranking table. New table supports independent track scores.
    ranking_rows = list(pages('job_rankings'))
    c.exec_driver_sql('ALTER TABLE job_rankings RENAME TO legacy_job_rankings_canonical_v1')
    metadata = MetaData()
    from ..models import Job
    Job.__table__.to_metadata(metadata)
    # Foreign-key dependencies are already in the database, only this table is created.
    table = JobRanking.__table__.to_metadata(metadata, name='canonical_rankings_new')
    table.indexes.clear()
    if postgres:
        # PostgreSQL keeps unique-index names after renaming the archived table.
        for constraint in table.constraints:
            if constraint.name:
                constraint.name = 'canonical_' + constraint.name
    table.create(c)
    winners = {}
    for row in ranking_rows:
        row['career_track'] = row.get('career_track') or old_tracks[row['job_id']]
        row['job_id'] = job_map[row['job_id']]
        key = (row['user_id'],row['job_id'],row['engine'],row['career_track'])
        if key not in winners or str(row['evaluated_at'] or '') > str(winners[key]['evaluated_at'] or ''): winners[key]=row
    for row in winners.values():
        row['stale'] = True  # Preserve score/evidence, validate against new routing before reuse.
        enqueue('INSERT INTO canonical_rankings_new ('+','.join(row)+') VALUES ('+','.join(':'+k for k in row)+')',row)
    flush()
    c.exec_driver_sql('ALTER TABLE canonical_rankings_new RENAME TO job_rankings')
    if postgres:
        # Explicit preserved IDs do not advance the new SERIAL sequence.
        c.execute(text("SELECT setval(pg_get_serial_sequence('job_rankings','id'), "
                       "COALESCE((SELECT MAX(id) FROM job_rankings),0)+1, false)"))
    c.exec_driver_sql('CREATE INDEX ix_canonical_ranking_lookup ON job_rankings(user_id,career_track,job_id,engine)')
    c.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_source_identity ON sources(identity_key)')
    c.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_job_identity ON jobs(canonical_key)')
    report['rankings_preserved'] = len(winners)
    report['rankings_archived'] = len(ranking_rows)
    report['sources_after'] = len(source_groups)
    report['jobs_after'] = len(groups)
    report['applications_preserved'] = len(applications)
    archive('__migration__',{'id':1,**report},0)
    flush()
    # Store report directly for idempotence without reading all data on repeat.
    c.execute(text("UPDATE catalog_migration_archive SET snapshot_json=:r WHERE entity_table='__migration__' AND entity_id=1"),dict(r=json.dumps(report,ensure_ascii=False)))
    return report
