import asyncio
import json

from app.collectors.official import (
    PRESETS,
    _extract_drushim_company_rows,
    _extract_structured_job_rows,
    _resolve_row_href,
)


def _one(identifier: str, payload: str):
    rows = _extract_structured_job_rows(payload, PRESETS[identifier])
    assert len(rows) == 1
    href, match = _resolve_row_href(rows[0], PRESETS[identifier])
    assert match is not None
    return rows[0], href, match.group(1)


def test_iai_api_object_becomes_canonical_job_row():
    row, href, external_id = _one(
        "iai",
        '{"jobs":[{"jobId":"76048939","title":"FPGA Design Engineer","city":"יהוד"}]}',
    )
    assert external_id == "76048939"
    assert href == "https://jobs.iai.co.il/job/76048939/"
    assert row["title"] == "FPGA Design Engineer"
    assert "יהוד" in row["text"]


def test_iai_live_feed_shape_becomes_complete_job_row():
    row, href, external_id = _one(
        "iai",
        '[{"id":76049533,"tl":"מהנדס/ת הנחיה ובקרה","dc":"תואר בהנדסת חשמל ופיתוח C++",'
        '"ct":"באר יעקב","tp":"משרה מלאה","jc":"הנדסה ופיתוח"}]',
    )
    assert external_id == "76049533"
    assert href == "https://jobs.iai.co.il/job/76049533/"
    assert row["title"] == "מהנדס/ת הנחיה ובקרה"
    assert "באר יעקב" in row["text"]
    assert "הנדסת חשמל" in row["text"]


def test_structured_feed_keeps_nested_description_but_drops_metadata_noise():
    row, _, _ = _one(
        "iai",
        json.dumps({"jobs": [{
            "jobId": "76048939", "title": "Embedded Engineer", "city": "יהוד",
            "description": {"html": "<p>3 years embedded software required</p>"},
            "trackingId": "d6fa6b68-42a0-4aba-bec7-c68b218c382e",
            "isActive": True,
        }]}),
    )
    assert "3 years embedded software required" in row["text"]
    assert "d6fa6b68" not in row["text"]


def test_rafael_api_object_becomes_canonical_job_row():
    row, href, external_id = _one(
        "rafael",
        '{"results":[{"jobNumber":13034,"jobTitle":"מהנדס/ת חומרה","location":"חיפה"}]}',
    )
    assert external_id == "13034"
    assert href == "https://career.rafael.co.il/job/13034/"
    assert row["title"] == "מהנדס/ת חומרה"


def test_rafael_drushim_fallback_keeps_official_id_link_and_job_details():
    payload = json.dumps({"Company": {"Jobs": [{
        "Code": 37897232,
        "SendCVButtonModel": {
            "ExternalLink": (
                "https://career.rafael.co.il/job?jobid=11431&referid=97"
                "https://career.rafael.co.il/job?jobid=11431&referid=97"
            ),
        },
        "JobInfo": {"EmployerJobCode": "7652"},
        "JobContent": {
            "Name": "פלנר.ית חומר – משרת בוגרי תעשייה וניהול",
            "Description": "<p>תכנון חומר לפרויקטים וניתוח המלצות MRP</p>",
            "Requirements": "<p>תואר בהנדסת תעשייה וניהול</p>",
            "Addresses": [{"City": "קריית ביאליק"}],
            "Experience": {"NameInHebrew": "ללא נסיון"},
        },
    }]}})
    rows = _extract_drushim_company_rows(payload, PRESETS["rafael"])
    assert len(rows) == 1
    href, match = _resolve_row_href(rows[0], PRESETS["rafael"])
    assert match is not None
    assert match.group(1) == "11431"
    assert href == "https://career.rafael.co.il/job?jobid=11431&referid=97"
    assert rows[0]["title"].startswith("פלנר.ית חומר")
    assert "קריית ביאליק" in rows[0]["text"]
    assert "תעשייה וניהול" in rows[0]["text"]


def test_rafael_drushim_fallback_rejects_non_rafael_apply_links():
    payload = json.dumps({"Company": {"Jobs": [{
        "SendCVButtonModel": {"ExternalLink": "https://example.com/job/9999"},
        "JobContent": {"Name": "Software Engineer"},
    }]}})
    assert _extract_drushim_company_rows(payload, PRESETS["rafael"]) == []


def test_elbit_api_object_becomes_canonical_job_row():
    row, href, external_id = _one(
        "elbit",
        '{"items":[{"jid":20895,"title":"Senior System Engineer","site":"Haifa"}]}',
    )
    assert external_id == "20895"
    assert "jid=20895" in href
    assert row["title"] == "Senior System Engineer"


def test_proteantecs_positions_keep_distinct_careerinfo_links():
    payload = '''{"positions":[
      {"pi":"F1.365-BE.103","title":"Senior Product Manager","location":"Tel Aviv"},
      {"pi":"8E.46F","title":"Logic Design Engineer","location":"Haifa"},
      {"pi":"5E.F5B","title":"Physical Design Engineer","location":"Haifa"}
    ]}'''
    rows = _extract_structured_job_rows(payload, PRESETS["proteantecs"])
    assert len(rows) == 3
    hrefs = {_resolve_row_href(row, PRESETS["proteantecs"])[0] for row in rows}
    assert len(hrefs) == 3
    assert "https://www.proteantecs.com/careerinfo?pi=F1.365-BE.103" in hrefs


def test_comeet_api_uses_its_canonical_hosted_url_and_nested_locations():
    payload = json.dumps([{
        "uid": "38.10A",
        "name": "Backend Engineer",
        "location": [{"name": "Tel Aviv"}, {"name": "Hybrid"}],
        "department": "Engineering",
        "url_comeet_hosted_page": (
            "https://www.comeet.com/jobs/Claroty/F2.004/backend-engineer/38.10A"
        ),
    }])
    row, href, external_id = _one("claroty", payload)
    assert external_id == "38.10A"
    assert href.endswith("/backend-engineer/38.10A")
    assert "Tel Aviv, Hybrid" in row["text"]


def test_comeet_api_extracts_full_details_and_city_from_location_object():
    payload = json.dumps([{
        "uid": "FA.E52",
        "name": "Backend Engineer",
        "location": {"name": "Israel", "city": "Tel Aviv"},
        "details": {"description": "Build secure backend systems", "requirements": "Python experience"},
        "url_comeet_hosted_page": "https://www.comeet.com/jobs/Claroty/F2.004/backend-engineer/FA.E52",
    }])
    row, _href, _external_id = _one("claroty", payload)
    assert "Tel Aviv" in row["text"]
    assert "Build secure backend systems" in row["text"]
    assert "Python experience" in row["text"]


def test_voyantis_comeet_feed_keeps_full_description_requirements_and_workplace():
    payload = json.dumps([{
        "uid": "89.E6C",
        "name": "AI-native software Engineer",
        "location": {"name": "Tel Aviv, Israel", "city": "Tel Aviv-Yafo"},
        "employment_type": "Full-time",
        "experience_level": "Mid",
        "workplace_type": "Hybrid",
        "details": [
            {"name": "Description", "value": "<p>Build ML and data pipelines on AWS.</p>"},
            {"name": "Requirements", "value": "<ul><li>Strong Python</li><li>3+ years of experience</li></ul>"},
        ],
        "url_comeet_hosted_page": "https://www.comeet.com/jobs/voyantis/86.00B/ai-native-software-engineer/89.E6C",
    }])
    row, href, external_id = _one("voyantis", payload)
    assert external_id == "89.E6C"
    assert href.endswith("/ai-native-software-engineer/89.E6C")
    assert "Build ML and data pipelines on AWS" in row["text"]
    assert "Strong Python" in row["text"]
    assert "3+ years of experience" in row["text"]
    assert row["workplace"] == "Hybrid"


def test_comeet_hydration_keeps_feed_route_when_branded_shell_has_template_heading(monkeypatch):
    from app.collectors.official import _hydrate_detail_rows

    class Response:
        status_code = 200
        text = '<html><head><link rel="canonical" href="https://claroty.com/open-positions/FA.E52"></head><body><main><h1>{{position.name}} @ {{company.name}}</h1></main></body></html>'
        url = "https://www.comeet.com/jobs/Claroty/F2.004/backend-engineer/FA.E52"

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def get(self, _url): return Response()

    monkeypatch.setattr("app.collectors.official.httpx.AsyncClient", lambda **_kwargs: Client())
    row = {
        "href": "https://www.comeet.com/jobs/Claroty/F2.004/backend-engineer/FA.E52",
        "title": "Backend Engineer",
        "linkText": "Backend Engineer",
        "text": "Backend Engineer Tel Aviv Engineering",
    }
    hydrated = asyncio.run(_hydrate_detail_rows([row], PRESETS["claroty"]))[0]
    assert hydrated["href"] == row["href"]
    assert hydrated["title"] == "Backend Engineer"


def test_palo_alto_hydration_drops_jobs_redirected_to_careers_home(monkeypatch):
    from app.collectors.official import _hydrate_detail_rows

    class Response:
        status_code = 200
        text = "<html><body><main><h1>Careers</h1></main></body></html>"
        url = "https://jobs.paloaltonetworks.com/en"

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def get(self, _url): return Response()

    monkeypatch.setattr("app.collectors.official.httpx.AsyncClient", lambda **_kwargs: Client())
    row = {
        "href": "https://jobs.paloaltonetworks.com/en/job/petah-tikva/data-engineer/47263/98323656112",
        "title": "Data Engineer", "linkText": "Data Engineer", "text": "Petach Tikva, Israel",
    }
    assert asyncio.run(_hydrate_detail_rows([row], PRESETS["paloalto"])) == []


def test_palo_alto_hydration_uses_job_heading_and_body_not_marketing_hero(monkeypatch):
    from app.collectors.official import _hydrate_detail_rows

    class Response:
        status_code = 200
        text = """
            <html><body><main>
              <h1>Revolutionizing protection.</h1>
              <section class="job-description section30__job-description">
                <h2 class="section30__job-title">Backend Engineer</h2>
                <span class="section30__job-info-location">Petach Tikva, Israel</span>
                <div class="ats-description">Build Python services. Requirements: 3+ years.</div>
              </section>
              <h3>Related Jobs</h3><p>Sales Manager in California</p>
            </main></body></html>
        """
        url = "https://jobs.paloaltonetworks.com/en/job/petah-tikva/backend-engineer/47263/100361908672"

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def get(self, _url): return Response()

    monkeypatch.setattr("app.collectors.official.httpx.AsyncClient", lambda **_kwargs: Client())
    row = {
        "href": Response.url,
        "title": "Backend Engineer", "linkText": "Backend Engineer", "text": "Israel",
    }
    hydrated = asyncio.run(_hydrate_detail_rows([row], PRESETS["paloalto"]))[0]
    assert hydrated["title"] == "Backend Engineer"
    assert "Petach Tikva, Israel" in hydrated["text"]
    assert "California" not in hydrated["text"]


def test_structured_adapter_rejects_unrelated_numeric_objects_without_job_title():
    payload = '{"analytics":{"id":76048939,"name":""},"page":{"id":76040000,"label":"Jobs"}}'
    assert _extract_structured_job_rows(payload, PRESETS["iai"]) == []


def test_unstable_large_boards_use_their_public_data_feeds():
    for identifier in ("iai", "proteantecs", "elbit"):
        preset = PRESETS[identifier]
        assert preset["data_url"].startswith("https://")
        assert preset["data_only"] is True


def test_problematic_comeet_boards_request_complete_structured_details():
    for identifier in ("vastdata", "silverfort", "paragon", "voyantis", "exodigo", "legitsecurity"):
        preset = PRESETS[identifier]
        assert preset["data_only"] is True
        assert "details=true" in preset["data_url"]


def test_monday_detail_hydration_is_not_skipped_when_listing_already_has_a_title():
    preset = PRESETS["monday"]
    assert preset["hydrate_details"] is True
    assert not preset.get("hydrate_missing_title_only")


def test_aqua_uses_the_job_slug_instead_of_the_full_card_as_title():
    preset = PRESETS["aqua"]
    assert preset["title_from_slug"] is True
    assert preset["title_path_offset"] == -2


def test_pliops_does_not_launch_a_browser_when_its_static_page_has_no_jobs():
    assert PRESETS["pliops"]["static_only"] is True


def test_comeet_embedded_positions_keep_full_descriptions_without_detail_download(monkeypatch):
    from types import SimpleNamespace
    import app.collectors.official as official
    description = 'Build secure software and test production services. ' * 6
    payload = [{'uid': 'AA.123', 'name': 'Software Engineer',
                'location': {'name': 'Tel Aviv, Israel'},
                'url_comeet_hosted_page': 'https://www.comeet.com/jobs/cyera/17.008/software-engineer/AA.123',
                'custom_fields': {'details': [{'name': 'Description', 'value': description}]}}]
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            calls.append(url)
            return SimpleNamespace(raise_for_status=lambda: None,
                text=f'<script>COMPANY_POSITIONS_DATA = {json.dumps(payload)};</script>')
    monkeypatch.setattr(official.httpx, 'AsyncClient', Client)
    jobs = asyncio.run(official.OfficialCareersCollector().collect('cyera'))
    assert len(jobs) == 1
    assert description.strip() in jobs[0].description
    assert jobs[0].location == 'Tel Aviv, Israel'
    assert calls == [PRESETS['cyera']['url']]
    assert jobs.complete is False


def test_cisco_job_schema_wins_over_shared_marketing_body():
    from bs4 import BeautifulSoup
    from app.collectors.official import _job_posting_detail
    payload = {'@type':'JobPosting','title':'ASIC Engineer',
               'description':'<p>Design circuits and verify interfaces.</p>',
               'jobLocation':{'address':{'addressLocality':'Caesarea','addressCountry':'IL'}}}
    soup = BeautifulSoup('<main><h1>We are Cisco</h1>Generic marketing</main>'
                         f'<script type="application/ld+json">{json.dumps(payload)}</script>', 'html.parser')
    title, text, location = _job_posting_detail(soup)
    assert location == "Caesarea, Israel"
    assert title == 'ASIC Engineer'
    assert 'Design circuits' in text
    assert 'Caesarea, Israel' in text
    assert 'Generic marketing' not in text


def test_generic_career_links_require_job_posting_evidence(monkeypatch):
    import app.collectors.official as official
    row = {'href':'https://example.com/careers/software', 'title':'Software Engineering',
           'linkText':'Software Engineering', 'text':'A department, not an open job. ' * 20}
    async def static(preset): return [row]
    async def hydrate(rows, preset): return rows
    monkeypatch.setattr(official, '_collect_static_rows', static)
    monkeypatch.setattr(official, '_hydrate_detail_rows', hydrate)
    monkeypatch.setitem(official.PRESETS, 'qa-generic', official._bounded_official_board('https://example.com/careers', 'QA'))
    import pytest
    with pytest.raises(official.PreserveExistingJobs):
        asyncio.run(official.OfficialCareersCollector().collect('qa-generic'))
    row['_verified_job'] = True
    assert len(asyncio.run(official.OfficialCareersCollector().collect('qa-generic'))) == 1


def test_one_accordion_jobs_keep_requirements_and_stable_links():
    from bs4 import BeautifulSoup
    from app.collectors.official import _extract_one_job_rows
    soup = BeautifulSoup('''<div id="company-job-opening"><div class="accordion_item" data-id="3558">
      <span class="job_title">Software Engineer</span><span>Tel Aviv, Israel</span>
      <div class="accordion_content">Python and SQL required. Three years of experience.
        <div class="accordion-footer">Share this job</div></div></div></div>
      <a href="/careers/">Careers</a>''', 'html.parser')
    rows = _extract_one_job_rows(soup)
    assert len(rows) == 1
    assert rows[0]['href'] == 'https://www.one1.co.il/?share_job_id=3558'
    assert 'Three years of experience' in rows[0]['text']
    assert 'Share this job' not in rows[0]['text']


def test_teva_embedded_jobs_use_matching_full_detail(monkeypatch):
    from types import SimpleNamespace
    import app.collectors.official as official
    position = {'id':123456, 'posting_name':'Software Engineer', 'location':'Tel Aviv, Israel',
                'canonicalPositionUrl':'https://www.careers.teva/careers/job/123456','job_description':''}
    description = 'Build reliable software and maintain production systems. ' * 5
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            calls.append(url)
            if '/api/' in url:
                text = json.dumps({**position, 'job_description':description})
            else:
                text = '<code id="smartApplyData">' + json.dumps({'positions':[position]}) + '</code>'
            return SimpleNamespace(status_code=200, text=text, raise_for_status=lambda:None)
    monkeypatch.setattr(official.httpx, 'AsyncClient', Client)
    jobs = asyncio.run(official.OfficialCareersCollector().collect('teva'))
    assert len(jobs) == 1
    assert description.strip() in jobs[0].description
    assert jobs[0].apply_url == position['canonicalPositionUrl']
    assert calls == [PRESETS['teva']['url'], 'https://www.careers.teva/api/apply/v2/jobs/123456?domain=tevapharm.com']
    assert not jobs.complete



def test_explicit_foreign_location_is_not_overridden_by_israel_in_description(monkeypatch):
    import app.collectors.official as official
    async def data(preset):
        return [{'href':'https://www.proteantecs.com/careerinfo?pi=AA.123',
                 'title':'Software Engineer', 'linkText':'Software Engineer',
                 'location':'New York, United States',
                 'text':'Software Engineer based in New York. Collaborate with our Israel headquarters. ' * 4}]
    monkeypatch.setattr(official, '_collect_data_rows', data)
    jobs = asyncio.run(official.OfficialCareersCollector().collect('proteantecs'))
    assert len(jobs) == 1
    assert jobs[0].location == ''
