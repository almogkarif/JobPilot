from app.collectors.official import PRESETS, _extract_structured_job_rows, _resolve_row_href


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


def test_rafael_api_object_becomes_canonical_job_row():
    row, href, external_id = _one(
        "rafael",
        '{"results":[{"jobNumber":13034,"jobTitle":"מהנדס/ת חומרה","location":"חיפה"}]}',
    )
    assert external_id == "13034"
    assert href == "https://career.rafael.co.il/job/13034/"
    assert row["title"] == "מהנדס/ת חומרה"


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
