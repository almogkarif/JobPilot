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


def test_structured_adapter_rejects_unrelated_numeric_objects_without_job_title():
    payload = '{"analytics":{"id":76048939,"name":""},"page":{"id":76040000,"label":"Jobs"}}'
    assert _extract_structured_job_rows(payload, PRESETS["iai"]) == []


def test_unstable_large_boards_use_their_public_data_feeds():
    for identifier in ("iai", "proteantecs", "elbit"):
        preset = PRESETS[identifier]
        assert preset["data_url"].startswith("https://")
        assert preset["data_only"] is True


def test_pliops_does_not_launch_a_browser_when_its_static_page_has_no_jobs():
    assert PRESETS["pliops"]["static_only"] is True
