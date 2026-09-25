"""Explicit local repair of reviewed permalink duplicates; never run at startup."""
from __future__ import annotations

import json
from sqlalchemy import MetaData, select, update, delete
from .unified_catalog import canonical_posting_url, canonical_job_key

VERSION = 'posting-permalink-v1'


def repair_posting_duplicates(engine, pairs, *, confirmed_local=False):
    """Retain old job IDs as aliases and archive every changed dependent record.

    Ambiguous parallel applications require separate review; this transaction
    refuses them instead of guessing which application/worker should survive.
    """
    url = engine.url
    if not confirmed_local or not (url.drivername.startswith('sqlite') or
            (url.host in {'127.0.0.1', 'localhost'} and (url.database or '').startswith('jobpilot_rehearsal_'))):
        raise RuntimeError('Repair requires an explicitly confirmed isolated local database')
    pairs = [(int(keep), int(alias)) for keep, alias in pairs]
    if len(pairs) > 100 or any(k == a for k, a in pairs) or len({a for _, a in pairs}) != len(pairs):
        raise ValueError('At most 100 distinct reviewed aliases are allowed')
    if {k for k, _ in pairs} & {a for _, a in pairs}:
        raise ValueError('Alias chains must be resolved before repair')
    metadata = MetaData()
    metadata.reflect(engine)
    tables = metadata.tables
    jobs, sources = tables['jobs'], tables['sources']
    archive = tables['catalog_migration_archive']
    report = {'version': VERSION, 'merged': 0, 'already_merged': 0}
    with engine.begin() as connection:
        def rows(name, condition):
            return list(connection.execute(select(tables[name]).where(condition)).mappings())
        def save(name, row, winner):
            entity = VERSION + ':' + name
            exists = connection.execute(select(archive.c.entity_id).where(
                archive.c.entity_table == entity, archive.c.entity_id == row['id'])).first()
            if not exists:
                connection.execute(archive.insert().values(entity_table=entity, entity_id=row['id'],
                    canonical_id=winner, migration_version=VERSION,
                    snapshot_json=json.dumps(dict(row), default=str, ensure_ascii=False)))
        for keep_id, alias_id in pairs:
            pair = {r['id']: r for r in connection.execute(select(jobs).where(jobs.c.id.in_([keep_id, alias_id])).with_for_update()).mappings()}
            if len(pair) != 2:
                raise ValueError('Reviewed job no longer exists')
            keep, alias = pair[keep_id], pair[alias_id]
            if alias['canonical_job_id'] == keep_id:
                report['already_merged'] += 1
                continue
            if keep['canonical_job_id'] or alias['canonical_job_id'] or keep['source_id'] != alias['source_id']:
                raise ValueError('Repair accepts canonical same-source postings only')
            normalize = lambda value: ' '.join(str(value or '').split()).casefold()
            if any(normalize(keep[field]) != normalize(alias[field]) for field in ('title', 'company', 'description')):
                raise ValueError('Posting content differs; manual review required')
            source = connection.execute(select(sources).where(sources.c.id == keep['source_id'])).mappings().one()
            posting = lambda job: canonical_posting_url(source['kind'], source['identifier'], job['external_id'], job['apply_url'])
            if not posting(keep) or posting(keep) != posting(alias):
                raise ValueError('Reviewed jobs do not share an exact posting permalink')
            apps = tables['applications']
            all_apps = rows('applications', apps.c.job_id.in_([keep_id, alias_id]) & apps.c.canonical_application_id.is_(None))
            if any(a['status'] == 'applying' for a in all_apps) or len({a['user_id'] for a in all_apps}) != len(all_apps):
                raise RuntimeError('Overlapping or in-flight applications require manual review')
            for app in all_apps:
                if app['job_id'] == alias_id:
                    save('applications', app, app['id'])
                    connection.execute(update(apps).where(apps.c.id == app['id']).values(job_id=keep_id))
            # Keep history and original IDs; children remain attached to unchanged
            # application IDs, so attempts/events/blockers need no rewrite.
            for name, keys in [('user_job_states', ['user_id']),
                               ('job_rankings', ['user_id', 'engine', 'career_track'])]:
                table = tables[name]
                for row in rows(name, table.c.job_id == alias_id):
                    condition = table.c.job_id == keep_id
                    for key in keys:
                        condition &= table.c[key] == row[key]
                    winner = connection.execute(select(table).where(condition)).mappings().first()
                    save(name, row, winner['id'] if winner else row['id'])
                    if winner:
                        save(name, winner, winner['id'])
                        if name == 'user_job_states':
                            weights = {'submitted':100, 'interview':100, 'offer':100, 'hidden':90, 'saved':80, 'queued':70, 'skipped':60, 'new':0}
                            status = max([winner['status'], row['status']], key=lambda s: weights.get(s, 50))
                            connection.execute(update(table).where(table.c.id == winner['id']).values(status=status))
                        connection.execute(delete(table).where(table.c.id == row['id']))
                    else:
                        connection.execute(update(table).where(table.c.id == row['id']).values(job_id=keep_id))
            drafts = tables['open_answer_drafts']
            for row in rows('open_answer_drafts', drafts.c.job_id == alias_id):
                save('open_answer_drafts', row, keep_id)
                connection.execute(update(drafts).where(drafts.c.id == row['id']).values(job_id=keep_id))
            tracks = tables['job_tracks']
            track_rows = rows('job_tracks', tracks.c.job_id == alias_id)
            save('job_tracks', {'id': alias_id, 'rows': [dict(r) for r in track_rows]}, keep_id)
            for row in track_rows:
                exists = connection.execute(select(tracks.c.job_id).where(tracks.c.job_id == keep_id, tracks.c.career_track == row['career_track'])).first()
                if not exists:
                    connection.execute(tracks.insert().values(**{**dict(row), 'job_id': keep_id}))
            connection.execute(delete(tracks).where(tracks.c.job_id == alias_id))
            identities = tables['job_source_identities']
            identity_rows = rows('job_source_identities', identities.c.job_id == alias_id)
            save('job_source_identities', {'id': alias_id, 'rows': [dict(r) for r in identity_rows]}, keep_id)
            connection.execute(update(identities).where(identities.c.job_id == alias_id).values(job_id=keep_id))
            for row in [keep, alias]:
                save('jobs', row, keep_id)
            connection.execute(update(jobs).where(jobs.c.id == alias_id).values(canonical_job_id=keep_id, is_active=False, canonical_key=None))
            connection.execute(update(jobs).where(jobs.c.id == keep_id).values(is_active=keep['is_active'] or alias['is_active'],
                canonical_key=canonical_job_key(source['kind'], source['identifier'], keep['external_id'], keep['apply_url'])))
            ranking = tables['job_rankings']
            connection.execute(update(ranking).where(ranking.c.job_id == keep_id).values(stale=True))
            report['merged'] += 1
    return report
