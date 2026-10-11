import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import random
import zlib

import pytest
from sqlalchemy import Text, create_engine, event, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, set_user_scope
from app.models import Job, JobRanking, Profile, Source
from app.ranking_storage import (
    DICTIONARY, DICTIONARY_SHA256, MAX_RANKING_STORAGE_BYTES,
    MIN_STORAGE_SAVING_BYTES, RankingStorageError, SQL_ELIGIBILITY_FIELDS,
    STORAGE_MARKER, decode_ranking_result, encode_ranking_result,
)
from app.services.matching import build_match_context
from app.services.ranking import service, v2
from tests.test_canonical_postgres import postgres_cluster
from tests.test_ranking_v2 import NOW, job, profile, score


DESCRIPTION = (
    "Develop backend Python software applications and distributed APIs. "
    "Requirements: Bachelor's degree in Computer Science and at least 3 years "
    "of software development experience. Python is required; Linux and SQL are preferred. "
    "Responsibilities include implementation, testing and reliable deployment."
)


@pytest.fixture
def payload(monkeypatch):
    monkeypatch.setattr(settings, 'unified_catalog_preview', False)
    candidate = profile(years=3, skills=['python', 'linux'], titles=['backend software engineer'])
    result = score(candidate, job('Backend Software Engineer', DESCRIPTION)).to_dict()
    result['_score_cache'] = {'fingerprint': 'a' * 64}
    result['extra'] = {'unicode': 'שלום 🌟', 'types': [True, None, 1, 1.25, '1']}
    return result


def serialized(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2)


def envelope_for(raw, *, dictionary=DICTIONARY, size=None, compressed=None):
    if compressed is None:
        compressor = zlib.compressobj(9, zdict=dictionary)
        compressed = compressor.compress(raw) + compressor.flush()
    return json.dumps({STORAGE_MARKER: 1, 'n': len(raw) if size is None else size,
                      'eligibility': {}, 'data': base64.b64encode(compressed).decode()},
                     separators=(',', ':'))


def test_lossless_storage_preserves_exact_original_string_and_sql_gates(payload):
    original = serialized(payload)
    encoded = encode_ranking_result(original)
    assert len(encoded.encode()) + MIN_STORAGE_SAVING_BYTES <= len(original.encode())
    stored = json.loads(encoded)
    assert stored[STORAGE_MARKER] == 1
    assert stored['n'] == len(original.encode())
    assert stored['eligibility'] == {k: payload['eligibility'][k] for k in SQL_ELIGIBILITY_FIELDS}
    assert decode_ranking_result(encoded) == original
    assert json.loads(decode_ranking_result(encoded)) == payload
    assert hashlib.sha256(DICTIONARY).hexdigest() == DICTIONARY_SHA256
    assert isinstance(JobRanking.__table__.c.result_json.type.impl, Text)


@pytest.mark.parametrize('original', [None, '', '{}', 'not JSON', '{broken',
                                      '{"value":NaN}', '{"_jp_rank":"legacy","n":7}'])
def test_short_invalid_and_legacy_values_are_not_reencoded(original):
    assert encode_ranking_result(original) == original
    assert decode_ranking_result(original) == original


def test_existing_marker_collision_in_ranking_payload_stays_plain(payload):
    payload[STORAGE_MARKER] = 1
    payload['n'] = 5
    payload['data'] = 'legacy field'
    original = serialized(payload)
    assert encode_ranking_result(original) == original
    assert decode_ranking_result(original) == original


@pytest.mark.parametrize('marker', [1, 2, 'legacy'])
def test_oversized_marker_leading_legacy_ranking_stays_plain(payload, monkeypatch, marker):
    # Even envelope-like legacy fields must not hide the actual v2 ranking.
    legacy = {STORAGE_MARKER: marker, 'n': 7, 'data': 'legacy field',
              'padding': 'א' * MAX_RANKING_STORAGE_BYTES, **payload}
    original = json.dumps(legacy, ensure_ascii=False, separators=(',', ':'))
    assert original.startswith('{"_jp_rank":')
    assert len(original.encode()) > MAX_RANKING_STORAGE_BYTES
    monkeypatch.setattr(zlib, 'decompressobj', lambda **_kwargs:
                        pytest.fail('Legacy ranking must not be decompressed'))
    assert encode_ranking_result(original) == original
    assert decode_ranking_result(original) == original


def test_oversized_or_incompressible_input_stays_plain(payload):
    payload['extra'] = 'א' * MAX_RANKING_STORAGE_BYTES
    oversized = serialized(payload)
    assert encode_ranking_result(oversized) == oversized
    assert decode_ranking_result(oversized) == oversized
    rng = random.Random(443)
    alphabet = ''.join(chr(value) for value in range(32, 127) if chr(value) not in {'"', '\\'})
    payload['extra'] = ''.join(rng.choice(alphabet) for _ in range(200_000))
    incompressible = json.dumps(payload, separators=(',', ':'))
    assert encode_ranking_result(incompressible) == incompressible


def test_exact_utf8_size_boundary_roundtrips(payload):
    payload['extra'] = ''
    original = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    payload['extra'] = 'x' * (MAX_RANKING_STORAGE_BYTES - len(original.encode()))
    original = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    assert len(original.encode()) == MAX_RANKING_STORAGE_BYTES
    assert decode_ranking_result(encode_ranking_result(original)) == original


@pytest.mark.parametrize('mutation', ['base64', 'truncated', 'trailing', 'length', 'version',
                                     'bool_version', 'bounds', 'gate', 'missing', 'extra'])
def test_corrupt_envelopes_fail_clearly(payload, mutation):
    envelope = json.loads(encode_ranking_result(serialized(payload)))
    if mutation == 'base64':
        envelope['data'] = '!not base64!'
    elif mutation in {'truncated', 'trailing'}:
        compressed = base64.b64decode(envelope['data'])
        compressed = compressed[:-1] if mutation == 'truncated' else compressed + b'trailing'
        envelope['data'] = base64.b64encode(compressed).decode()
    elif mutation == 'length':
        envelope['n'] -= 1
    elif mutation == 'version':
        envelope[STORAGE_MARKER] = 2
    elif mutation == 'bool_version':
        envelope[STORAGE_MARKER] = True
    elif mutation == 'bounds':
        envelope['n'] = MAX_RANKING_STORAGE_BYTES + 1
    elif mutation == 'gate':
        envelope['eligibility']['degree_status'] = 'different'
    elif mutation == 'missing':
        del envelope['data']
    else:
        envelope['unexpected'] = True
    with pytest.raises(RankingStorageError):
        decode_ranking_result(json.dumps(envelope, separators=(',', ':')))


@pytest.mark.parametrize('raw', [b'x' * (MAX_RANKING_STORAGE_BYTES + 1), b'not JSON', b'\xff'])
def test_decoder_rejects_bombs_invalid_json_and_invalid_utf8(raw):
    with pytest.raises(RankingStorageError):
        decode_ranking_result(envelope_for(raw, size=min(len(raw), MAX_RANKING_STORAGE_BYTES)))


def test_decoder_rejects_wrong_dictionary_and_oversized_stored_envelope(payload, monkeypatch):
    with pytest.raises(RankingStorageError):
        decode_ranking_result(envelope_for(serialized(payload).encode(), dictionary=b'another dictionary'))
    encoded = json.loads(encode_ranking_result(serialized(payload)))
    encoded['data'] = 'a' * MAX_RANKING_STORAGE_BYTES
    monkeypatch.setattr(base64, 'b64decode', lambda *_args, **_kwargs:
                        pytest.fail('Oversized envelope must fail before base64 allocation'))
    monkeypatch.setattr(zlib, 'decompressobj', lambda **_kwargs:
                        pytest.fail('Oversized envelope must fail before decompression'))
    with pytest.raises(RankingStorageError):
        decode_ranking_result(json.dumps(encoded, separators=(',', ':')))
    with pytest.raises(RankingStorageError):
        decode_ranking_result('  ' + json.dumps(encoded, separators=(',', ':')))
    with pytest.raises(RankingStorageError):
        decode_ranking_result('{"_jp_rank":1,"n":broken')


@pytest.fixture(params=['sqlite', 'postgresql'])
def storage_database(monkeypatch, request):
    monkeypatch.setattr(settings, 'unified_catalog_preview', False)
    if request.param == 'postgresql':
        from uuid import uuid4
        cluster = request.getfixturevalue('postgres_cluster')
        name = 'jobpilot_rehearsal_' + uuid4().hex
        with cluster.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_engine(cluster.url.set(database=name))
    else:
        cluster = None
        engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    @contextmanager
    def sessions(owner='ranking-storage-one'):
        with Session(engine, expire_on_commit=False) as db:
            set_user_scope(db, owner)
            yield db
    with sessions() as db:
        db.add(Source(id=1, name='Synthetic storage', kind='greenhouse', identifier='synthetic-storage'))
        db.add(Job(id=1, source_id=1, external_id='synthetic-storage', title='Backend Software Engineer',
                   company='Synthetic', description=DESCRIPTION, location='Tel Aviv, Israel', workplace='hybrid',
                   career_track='computer_science', published_at=datetime.now(timezone.utc),
                   apply_url='https://example.com/synthetic-storage'))
        db.commit()
    for owner, skills in [('ranking-storage-one', ['python', 'linux']), ('ranking-storage-two', ['docker'])]:
        with sessions(owner) as db:
            db.add(Profile(active_career_track='computer_science', years_experience=3,
                           years_experience_options_json='["3"]', skills_json=json.dumps(skills),
                           desired_titles_json='["backend software engineer"]',
                           preferred_locations_json='["Israel"]', application_profile_json='{"degree_level":"bachelor"}'))
            db.commit()
    try:
        yield engine, sessions
    finally:
        engine.dispose()
        if cluster is not None:
            with cluster.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}"'))


def test_real_persistence_cache_hide_restore_and_sql_diagnostics(storage_database, monkeypatch):
    engine, sessions = storage_database
    with sessions() as db:
        p = db.scalar(select(Profile))
        opening = db.get(Job, 1)
        config = service.get_settings(db)
        row = service.persist_v2_result(db, opening, p, config)
        db.flush()
        original, row_id, original_score = row.result_json, row.id, row.score
        db.commit()
    with engine.connect() as connection:
        stored = connection.execute(text('SELECT result_json FROM job_rankings WHERE id=:id'), {'id': row_id}).scalar_one()
        assert json.loads(stored)[STORAGE_MARKER] == 1
        expected = json.loads(original)['eligibility']
        if engine.dialect.name == 'postgresql':
            gates = connection.execute(text("SELECT result_json::jsonb->'eligibility' FROM job_rankings WHERE id=:id"), {'id': row_id}).scalar_one()
        else:
            gates = json.loads(connection.execute(text("SELECT json_extract(result_json,'$.eligibility') FROM job_rankings WHERE id=:id"), {'id': row_id}).scalar_one())
        assert gates == {key: expected[key] for key in SQL_ELIGIBILITY_FIELDS}
    with sessions() as db:
        row = db.get(JobRanking, row_id)
        assert row.result_json == original
        p, opening, config = db.scalar(select(Profile)), db.get(Job, 1), service.get_settings(db)
        p.excluded_keywords_json = '["backend"]'
        service.persist_v2_result(db, opening, p, config, existing_row=row)
        hidden = json.loads(row.result_json)
        assert hidden['breakdown'] == {}
        assert hidden['_score_cache']['breakdown'] == json.loads(original)['breakdown']
        assert hidden['eligibility']['explicit_exclusion']
        db.commit()
    with sessions() as db:
        row = db.get(JobRanking, row_id)
        assert json.loads(row.result_json) == hidden
        p, opening, config = db.scalar(select(Profile)), db.get(Job, 1), service.get_settings(db)
        p.excluded_keywords_json = '[]'
        def no_recompute(*args, **kwargs):
            raise AssertionError('Decoded hidden scoring cache must restore without rescoring skills')
        monkeypatch.setattr(v2, 'score_skills', no_recompute)
        service.persist_v2_result(db, opening, p, config, existing_row=row)
        assert row.score == original_score
        assert json.loads(row.result_json)['breakdown'] == json.loads(original)['breakdown']
        db.commit()


def test_legacy_and_encoded_rows_coexist_with_tenant_scores_and_no_extra_reads(storage_database):
    engine, sessions = storage_database
    expected = {}
    for owner in ('ranking-storage-one', 'ranking-storage-two'):
        with sessions(owner) as db:
            row = service.persist_v2_result(db, db.get(Job, 1), db.scalar(select(Profile)), service.get_settings(db))
            expected[owner] = row.result_json, row.score, row.id
            db.commit()
    assert expected['ranking-storage-one'][1] != expected['ranking-storage-two'][1]
    # Preserve an existing plain row alongside new encoded rows, without an ORM bind.
    with engine.begin() as connection:
        connection.execute(text('UPDATE job_rankings SET result_json=:plain WHERE id=:id'),
                           {'plain': expected['ranking-storage-one'][0], 'id': expected['ranking-storage-one'][2]})
    statements = []
    def capture(_c, _cu, sql, _params, _context, _many):
        if sql.lstrip().lower().startswith('select'):
            statements.append(sql)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        for owner in expected:
            with sessions(owner) as db:
                rows = db.scalars(select(JobRanking)).all()
                assert len(rows) == 1
                assert (rows[0].result_json, rows[0].score) == expected[owner][:2]
        assert len(statements) == 2
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
