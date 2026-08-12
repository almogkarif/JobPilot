#!/usr/bin/env python3
from pathlib import Path
import subprocess

EXPECTED_HEAD_PREFIX = "4bb2a2e"

def die(msg):
    raise SystemExit(f"\n❌ {msg}\n")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly 1 anchor, found {count}. No files were written.")
    return text.replace(old, new, 1)

def main():
    root = Path.cwd()
    if not (root / ".git").exists():
        die("Run this script from the JobPilot repository root.")

    head = subprocess.check_output(
        ["git", "rev-parse", "--short=12", "HEAD"], text=True
    ).strip()
    if not head.startswith(EXPECTED_HEAD_PREFIX):
        die(
            f"Expected HEAD {EXPECTED_HEAD_PREFIX}…, found {head}. "
            "Stop here so we do not edit a different code baseline."
        )

    official_path = root / "app/collectors/official.py"
    appjs_path = root / "app/static/app.js"
    index_path = root / "app/static/index.html"

    for path in (official_path, appjs_path, index_path):
        if not path.exists():
            die(f"Missing expected file: {path}")

    official = official_path.read_text()
    appjs = appjs_path.read_text()
    index = index_path.read_text()

    # 1) Official careers reliability.
    official = replace_once(
        official,
        '"ibm": {"url": "https://www.ibm.com/careers/search?field_keyword_05[0]=Israel", "selector": \'a[href*="/careers/"][href*="job"]\', "id_pattern": r"(?:job|jobs)[^A-Za-z0-9]+([A-Za-z0-9_-]{5,})", "company": "IBM", "allow_empty": True, "empty_markers": ("0 of 0 items", "1 – 0 of 0 items", "1 - 0 of 0 items")},',
        '"ibm": {"url": "https://www.ibm.com/careers/search?field_keyword_05[0]=Israel", "selector": \'a[href*="/careers/"][href*="job"]\', "id_pattern": r"(?:job|jobs)[^A-Za-z0-9]+([A-Za-z0-9_-]{5,})", "company": "IBM", "allow_empty": True, "empty_markers": ("0 of 0 items", "1 – 0 of 0 items", "1 - 0 of 0 items", "0 jobs", "no jobs found", "no results")},',
        "IBM empty result handling",
    )

    official = replace_once(
        official,
        '"salesforce": {"url": "https://careers.salesforce.com/en/jobs/?country=Israel", "selector": \'a[href*="jr"], [data-href*="jr"], [data-url*="jr"]\', "id_pattern": r"(?i)(jr\\d+)", "company": "Salesforce", "title_from_slug": True, "settle_ms": 3500, "selector_timeout_ms": 22000, "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 80},',
        '"salesforce": {"url": "https://www.salesforce.com/company/careers/jobs/?country=Israel", "selector": \'a[href*="jr"], [data-href*="jr"], [data-url*="jr"]\', "id_pattern": r"(?i)(jr\\d+)", "company": "Salesforce", "title_from_slug": True, "settle_ms": 3500, "selector_timeout_ms": 22000, "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 80, "dynamic_scroll": True},',
        "Salesforce current careers URL",
    )

    official = replace_once(
        official,
        '"elbit": {"url": "https://elbitsystemscareer.com/jobs/", "selector": \'a[href*="/job/"][href*="jid="], a[href*="jid="], [data-url*="jid="], [onclick*="jid="]\', "id_pattern": r"[?&]jid=(\\d+)", "company": "Elbit Systems", "load_more_text": "תוצאות חיפוש נוספות", "settle_ms": 3000, "selector_timeout_ms": 22000, "prefer_link_text": True, "http_first": True, "href_template": "https://elbitsystemscareer.com/job/?jid={id}", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 100},',
        '"elbit": {"url": "https://elbitsystemscareer.com/jobs/", "selector": \'a[href*="/job/"][href*="jid="], a[href*="jid="], [data-href*="jid="], [data-url*="jid="], [onclick*="jid="]\', "id_pattern": r"[?&]jid=/?(\\d+)", "company": "Elbit Systems", "load_more_text": "תוצאות חיפוש נוספות", "settle_ms": 3000, "selector_timeout_ms": 22000, "prefer_link_text": True, "http_first": True, "href_template": "https://elbitsystemscareer.com/job/?jid={id}", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 100, "dynamic_scroll": True},',
        "Elbit selectors",
    )

    official = replace_once(
        official,
        '"rafael": {"url": "https://career.rafael.co.il/search/", "selector": \'a[href*="/job/"], [data-url*="/job/"], [onclick*="/job/"]\', "id_pattern": r"/job/(\\d+)/?", "company": "Rafael", "http_first": True, "selector_timeout_ms": 22000, "prefer_link_text": True, "href_template": "https://career.rafael.co.il/job/{id}/", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 90},',
        '"rafael": {"url": "https://career.rafael.co.il/search/", "selector": \'a[href*="/job/"], [data-href*="/job/"], [data-url*="/job/"], [onclick*="/job/"]\', "id_pattern": r"/job/(\\d+)/?", "company": "Rafael", "http_first": True, "selector_timeout_ms": 22000, "prefer_link_text": True, "href_template": "https://career.rafael.co.il/job/{id}/", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 90, "dynamic_scroll": True},',
        "Rafael selectors",
    )

    official = replace_once(
        official,
        '"iai": {"url": "https://jobs.iai.co.il/jobs/", "selector": \'a[href*="/job/"]\', "id_pattern": r"/job/(\\d+)/", "company": "Israel Aerospace Industries"},',
        '"iai": {"url": "https://jobs.iai.co.il/jobs/", "selector": \'a[href*="/job/"], [data-href*="/job/"], [data-url*="/job/"], [onclick*="/job/"]\', "id_pattern": r"/job/(\\d+)/?", "company": "Israel Aerospace Industries", "selector_timeout_ms": 22000, "raw_id_fallback": True, "dynamic_scroll": True},',
        "IAI selectors",
    )

    official = replace_once(
        official,
        '                links = page.locator(preset["selector"])\n',
        '''                if preset.get("dynamic_scroll"):
                    for fraction in (0.25, 0.5, 0.75, 1.0):
                        await page.evaluate(
                            "(fraction) => window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) * fraction)",
                            fraction,
                        )
                        await page.wait_for_timeout(550)
                    await page.evaluate("window.scrollTo(0, 0)")
                    await page.wait_for_timeout(350)
                links = page.locator(preset["selector"])
''',
        "Dynamic-board scrolling",
    )

    official = official.replace(
        'page.locator("a[href], [onclick]")',
        'page.locator("a[href], [onclick], [data-href], [data-url]")',
    )
    official = official.replace(
        "parent.querySelectorAll('a[href], [onclick]').length",
        "parent.querySelectorAll('a[href], [onclick], [data-href], [data-url]').length",
    )
    official = official.replace(
        "generic = soup.select(\"a[href], [onclick]\")",
        "generic = soup.select(\"a[href], [onclick], [data-href], [data-url]\")",
    )

    official = replace_once(
        official,
        '" ".join((str(element.get("href") or ""), str(element.get("onclick") or ""))),',
        '" ".join((str(element.get("href") or ""), str(element.get("data-href") or ""), str(element.get("data-url") or ""), str(element.get("onclick") or ""))),',
        "Static generic identifier search",
    )

    official = replace_once(
        official,
        '''            "href": str(element.get("href") or ""),
            "onclick": str(element.get("onclick") or ""),
''',
        '''            "href": str(element.get("href") or ""),
            "dataHref": str(element.get("data-href") or ""),
            "dataUrl": str(element.get("data-url") or ""),
            "onclick": str(element.get("onclick") or ""),
''',
        "Static row data attributes",
    )

    # Add data-href/data-url to both Playwright row shapes.
    first_shape = '''                             href: a.getAttribute('href') || '',
                             onclick: a.getAttribute('onclick') || '',
'''
    first_shape_new = '''                             href: a.getAttribute('href') || '',
                             dataHref: a.getAttribute('data-href') || '',
                             dataUrl: a.getAttribute('data-url') || '',
                             onclick: a.getAttribute('onclick') || '',
'''
    if first_shape in official:
        official = replace_once(official, first_shape, first_shape_new, "Rendered generic row data attributes")

    second_shape = '''                         href: a.getAttribute('href') || '',
                         onclick: a.getAttribute('onclick') || '',
'''
    second_shape_new = '''                         href: a.getAttribute('href') || '',
                         dataHref: a.getAttribute('data-href') || '',
                         dataUrl: a.getAttribute('data-url') || '',
                         onclick: a.getAttribute('onclick') || '',
'''
    if second_shape in official:
        official = replace_once(official, second_shape, second_shape_new, "Rendered selector row data attributes")

    official = replace_once(
        official,
        '''    raw_href = str(row.get("href") or "").strip()
    onclick = str(row.get("onclick") or "").strip()
    base_url = str(preset["url"])
    href = urljoin(base_url, raw_href) if raw_href else ""
    searchable = " ".join(part for part in (href, raw_href, onclick) if part)
''',
        '''    raw_href = str(row.get("href") or "").strip()
    data_href = str(row.get("dataHref") or row.get("data-href") or "").strip()
    data_url = str(row.get("dataUrl") or row.get("data-url") or "").strip()
    onclick = str(row.get("onclick") or "").strip()
    base_url = str(preset["url"])
    raw_target = raw_href or data_href or data_url
    href = urljoin(base_url, raw_target) if raw_target else ""
    searchable = " ".join(part for part in (href, raw_href, data_href, data_url, onclick) if part)
''',
        "Resolve data-href/data-url",
    )

    # 2) Checkbox/card interaction collision.
    appjs = replace_once(
        appjs,
        '''function highlightSelectedCard(target) {
  const selected = target?.closest?.(selectableCardSelector);
  $$('.is-card-selected').forEach((card) => {
    if (card !== selected) card.classList.remove('is-card-selected');
  });
  selected?.classList.add('is-card-selected');
}
''',
        '''function highlightSelectedCard(target) {
  if (target?.closest?.('input, button, select, textarea, a, label, [role="button"]')) {
    $$('.is-card-selected').forEach((card) => card.classList.remove('is-card-selected'));
    return;
  }
  const selected = target?.closest?.(selectableCardSelector);
  $$('.is-card-selected').forEach((card) => {
    if (card !== selected) card.classList.remove('is-card-selected');
  });
  selected?.classList.add('is-card-selected');
}
''',
        "Interactive controls vs card highlight",
    )

    # 3) Resume suggestion feedback should be immediate after API success.
    appjs = replace_once(
        appjs,
        '''    updateProfileDirtyState(); updateProfileSectionSummaries(); updateProfileCompletion();
    await loadResumeInsights();
    toast(field==='skills'?'הסקיל נוסף לפרופיל והמשרות דורגו מחדש':'הפרט נוסף לפרופיל');
''',
        '''    updateProfileDirtyState(); updateProfileSectionSummaries(); updateProfileCompletion();
    if (button?.isConnected) button.remove();
    toast(field==='skills'?'הסקיל נוסף לפרופיל והמשרות דורגו מחדש':'הפרט נוסף לפרופיל');
    loadResumeInsights().catch((error) => console.warn('Resume insights refresh failed', error));
''',
        "Resume suggestion immediate feedback",
    )

    index = replace_once(
        index,
        '<script src="/static/app.js?v=0.25.0"></script>',
        '<script src="/static/app.js?v=0.25.1"></script>',
        "app.js cache version",
    )

    official_path.write_text(official)
    appjs_path.write_text(appjs)
    index_path.write_text(index)

    print("✅ JobPilot reliability updater applied successfully.")
    print("Changed:")
    print("  - app/collectors/official.py")
    print("  - app/static/app.js")
    print("  - app/static/index.html")
    print("\nNext:")
    print("  git diff --check")
    print("  python -m pytest -q")

if __name__ == "__main__":
    main()
