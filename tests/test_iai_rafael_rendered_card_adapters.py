from app.collectors.official import PRESETS, _dedupe_rows, _resolve_row_href


def test_iai_and_rafael_accept_deterministic_listing_fallback_ids():
    for identifier in ("iai", "rafael"):
        preset = PRESETS[identifier]
        href = preset["url"] + ("&" if "?" in preset["url"] else "?") + "jp_job=0123456789abcdef"
        resolved, match = _resolve_row_href({"href": href}, preset)
        assert match is not None
        assert match.group(1) == "0123456789abcdef"
        assert resolved == href


def test_listing_fallback_rows_dedupe_without_guessing_detail_url():
    preset = PRESETS["iai"]
    href = "https://jobs.iai.co.il/jobs/?jp_job=0123456789abcdef"
    rows = _dedupe_rows([
        {"href": href, "title": "מהנדס/ת FPGA", "text": "לחטיבה דרוש/ה מהנדס/ת FPGA ניסיון VHDL"},
        {"href": href, "title": "מהנדס/ת FPGA", "text": "duplicate"},
    ], preset)
    assert len(rows) == 1
    assert rows[0]["href"] == href
