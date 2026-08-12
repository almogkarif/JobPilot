import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collectors.greenhouse import GreenhouseCollector
from app.collectors.lever import LeverCollector
from app.collectors.smartrecruiters import SmartRecruitersCollector
from app.collectors.workday import WORKDAY_PRESETS, _normalize_applied_location
from app.database import Base
from app.models import Profile, Source
from app.services.source_repair import repair_error_sources


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(Profile(id=1, full_name="Test", location="Israel"))
    db.commit()
    return db


def test_known_errored_sources_migrate_and_are_reenabled_for_targeted_retry():
    db = _session()
    disabled = datetime.now(timezone.utc) + timedelta(hours=12)
    rows = [
        Source(name="Applied", kind="official_careers", identifier="applied-materials", company_name="Applied Materials", last_error="old selector", disabled_until=disabled),
        Source(name="Similarweb", kind="official_careers", identifier="similarweb", company_name="Similarweb", last_error="dead domain", disabled_until=disabled),
        Source(name="Outbrain", kind="official_careers", identifier="outbrain", company_name="Outbrain", last_error="old selector", disabled_until=disabled),
        Source(name="CyberArk", kind="official_careers", identifier="cyberark", company_name="CyberArk", last_error="old selector", disabled_until=disabled),
        Source(name="Mobileye", kind="official_careers", identifier="mobileye", company_name="Mobileye", last_error="", disabled_until=disabled),
        Source(name="Taboola", kind="official_careers", identifier="taboola", company_name="Taboola", last_error="", disabled_until=disabled),
        Source(name="Orca", kind="official_careers", identifier="orca", company_name="Orca Security", last_error="", disabled_until=disabled),
        Source(name="Wix", kind="official_careers", identifier="wix", company_name="Wix", last_error="old selector", disabled_until=disabled),
        Source(name="Working custom", kind="greenhouse", identifier="custom", company_name="Custom", last_error="", disabled_until=disabled),
    ]
    db.add_all(rows)
    db.commit()

    result = repair_error_sources(db)

    assert set(result["source_ids"]) == {row.id for row in rows[:8]}
    assert (rows[0].kind, rows[0].identifier) == ("workday", "applied-materials")
    assert (rows[1].kind, rows[1].identifier) == ("greenhouse", "similarweb")
    assert (rows[2].kind, rows[2].identifier) == ("greenhouse", "outbraininc")
    assert (rows[3].kind, rows[3].identifier) == ("smartrecruiters", "Cyberark1")
    assert (rows[4].kind, rows[4].identifier) == ("lever", "eu:mobileye")
    assert (rows[5].kind, rows[5].identifier) == ("greenhouse", "taboola")
    assert (rows[6].kind, rows[6].identifier) == ("greenhouse", "orcasecurity")
    assert rows[7].kind == "official_careers"
    assert all(row.disabled_until is None for row in rows[:8])
    assert all(row.last_error for row in rows[:4])  # errors remain until retries succeed
    assert rows[8].disabled_until is not None
    db.close()


def test_already_migrated_source_with_error_is_retried_again_after_interrupted_startup():
    db = _session()
    source = Source(
        name="CyberArk", kind="smartrecruiters", identifier="Cyberark1", company_name="CyberArk",
        last_error="network interrupted", disabled_until=datetime.now(timezone.utc) + timedelta(hours=4),
    )
    db.add(source)
    db.commit()
    result = repair_error_sources(db)
    assert result["source_ids"] == [source.id]
    assert source.disabled_until is None
    db.close()


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSmartClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None):
        self.calls.append((url, params))
        if url.endswith("/postings"):
            return _FakeResponse({
                "totalFound": 1,
                "content": [{
                    "id": "job-1", "name": "Backend Engineer",
                    "location": {"city": "Petah Tikva", "countryCode": "il"},
                    "ref": "https://api.smartrecruiters.com/v1/companies/Cyberark1/postings/job-1",
                }],
            })
        return _FakeResponse({
            "id": "job-1", "name": "Backend Engineer",
            "location": {"city": "Petah Tikva", "country": "Israel", "countryCode": "il"},
            "applyUrl": "https://jobs.smartrecruiters.com/Cyberark1/job-1",
            "releasedDate": "2026-08-10T09:00:00Z",
            "jobAd": {"sections": {
                "jobDescription": {"title": "What you will do", "text": "<p>Build secure services.</p>"},
                "qualifications": {"title": "Qualifications", "text": "<ul><li>Python</li></ul>"},
            }},
        })


def test_smartrecruiters_collector_uses_public_posting_api_and_parses_israel_job(monkeypatch):
    from app.collectors import smartrecruiters as module

    _FakeSmartClient.calls = []
    monkeypatch.setattr(module.httpx, "AsyncClient", _FakeSmartClient)
    jobs = asyncio.run(SmartRecruitersCollector().collect("Cyberark1", "CyberArk"))

    assert len(jobs) == 1
    job = jobs[0]
    assert job.external_id == "job-1"
    assert job.title == "Backend Engineer"
    assert job.company == "CyberArk"
    assert job.location == "Petah Tikva, Israel"
    assert "What you will do" in job.description
    assert "Build secure services" in job.description
    assert _FakeSmartClient.calls[0][1]["country"] == "il"


class _FakeGreenhouseClient:
    urls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None):
        self.urls.append(url)
        return _FakeResponse({"jobs": []})


def test_greenhouse_eu_prefix_uses_documented_job_board_api_host(monkeypatch):
    from app.collectors import greenhouse as module

    _FakeGreenhouseClient.urls = []
    monkeypatch.setattr(module.httpx, "AsyncClient", _FakeGreenhouseClient)
    asyncio.run(GreenhouseCollector().collect("eu:outbraininc", "Outbrain"))
    assert _FakeGreenhouseClient.urls == ["https://boards-api.greenhouse.io/v1/boards/outbraininc/jobs"]


def test_applied_materials_has_verified_workday_preset_and_location_normalizer():
    assert WORKDAY_PRESETS["applied-materials"][:3] == ("amat.wd1.myworkdayjobs.com", "amat", "External")
    assert _normalize_applied_location("Rehovot, ISR", "") == "Rehovot, Israel"


class _FakeLeverClient:
    urls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None):
        self.urls.append(url)
        return _FakeResponse([])


def test_lever_eu_prefix_uses_european_api_host(monkeypatch):
    from app.collectors import lever as module

    _FakeLeverClient.urls = []
    monkeypatch.setattr(module.httpx, "AsyncClient", _FakeLeverClient)
    asyncio.run(LeverCollector().collect("eu:mobileye", "Mobileye"))
    assert _FakeLeverClient.urls == ["https://api.eu.lever.co/v0/postings/mobileye"]


def test_greenhouse_prefers_first_published_over_updated_at(monkeypatch):
    from app.collectors import greenhouse as module

    class Client(_FakeGreenhouseClient):
        async def get(self, url, params=None):
            return _FakeResponse({"jobs": [{
                "id": 1, "title": "Engineer", "location": {"name": "Tel Aviv, Israel"},
                "content": "Build things", "absolute_url": "https://example.com/job/1",
                "first_published": "2026-08-01T10:00:00Z",
                "updated_at": "2026-08-10T10:00:00Z",
            }]})

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    jobs = asyncio.run(GreenhouseCollector().collect("taboola", "Taboola"))
    assert jobs[0].published_at.isoformat().startswith("2026-08-01T10:00:00")
