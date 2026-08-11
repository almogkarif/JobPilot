from app.collectors.official import PRESETS, _extract_israel_location, _extract_raw_rows, _resolve_row_href


def _id(identifier: str, href: str = "", onclick: str = "") -> tuple[str, str]:
    resolved, match = _resolve_row_href({"href": href, "onclick": onclick}, PRESETS[identifier])
    assert match is not None
    return resolved, match.group(1)


def test_checkpoint_accepts_current_detail_url_and_onclick_fallback():
    url, external_id = _id(
        "checkpoint",
        "https://careers.checkpoint.com/index.php?a=show&joborderid=8500875&m=cpcareers",
    )
    assert external_id == "8500875"
    assert "joborderid=8500875" in url

    url, external_id = _id("checkpoint", onclick="openJob('joborderid=1752419')")
    assert external_id == "1752419"
    assert url.endswith("a=show&joborderid=1752419&m=cpcareers")


def test_salesforce_accepts_localized_and_redirected_jr_urls():
    _, external_id = _id("salesforce", "https://careers.salesforce.com/it/lavori/jr280655/senior-product-manager/")
    assert external_id.casefold() == "jr280655"
    _, external_id = _id("salesforce", "https://www.salesforce.com/company/careers/jobs/jr297651/senior-lead-full-stack-engineer/")
    assert external_id.casefold() == "jr297651"


def test_wix_accepts_new_position_seat_urls_and_legacy_location_urls():
    _, external_id = _id(
        "wix",
        "https://careers.wix.com/position/seat-2226ea04-1827-4635-ba83-f3e34bc69aa7-744000017110845",
    )
    assert external_id.startswith("seat-")
    _, external_id = _id("wix", "https://careers.wix.com/location/tel-aviv/positions/3608")
    assert external_id == "3608"


def test_elbit_uses_current_jid_detail_urls():
    _, external_id = _id("elbit", "https://elbitsystemscareer.com/job/?jid=20409")
    assert external_id == "20409"


def test_rafael_and_appsflyer_current_job_urls():
    _, external_id = _id("rafael", "https://career.rafael.co.il/job/5353/?referid=324")
    assert external_id == "5353"
    _, external_id = _id(
        "appsflyer",
        "https://careers.appsflyer.com/jobs/position/8509670002/product-partnerships-manager/?rd=1",
    )
    assert external_id == "8509670002"


def test_hebrew_job_card_locations_are_normalized_to_israel():
    assert _extract_israel_location("מזהה דרישה: 6563 מיקום: חיפה") == "Haifa, Israel"
    assert _extract_israel_location("מיקום: ראש העין") == "Rosh HaAyin, Israel"
    assert _extract_israel_location("משרה מלאה מכון דוד - קריות") == "Krayot, Israel"
    assert _extract_israel_location("מכון לשם - גוש שגב") == "Misgav, Israel"


def test_script_json_job_urls_are_recovered_when_dom_selectors_change():
    fixtures = {
        "checkpoint": '<script>{"url":"/index.php?a=show&joborderid=8500875&m=cpcareers"}</script>',
        "salesforce": '<script>{"href":"/it/lavori/jr344572/mid-level-fullstack-engineer/"}</script>',
        "rafael": '<div data-state=\'{"job":"/job/12637/"}\'></div>',
        "elbit": '<script>window.jobs=[{"url":"/job/?jid=20161"},{"url":"/job/?jid=20747"}]</script>',
        "appsflyer": '<script>{"url":"/jobs/position/8636474002/backend-engineer/?rd=1"}</script>',
    }
    for identifier, html in fixtures.items():
        rows = _extract_raw_rows(html, PRESETS[identifier])
        assert rows, identifier
        _, match = _resolve_row_href(rows[0], PRESETS[identifier])
        assert match is not None, identifier
