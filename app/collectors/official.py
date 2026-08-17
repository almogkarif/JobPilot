from __future__ import annotations

import asyncio
import html as html_lib
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .base import NormalizedJob, PreserveExistingJobs


PRESETS = {
    # Electrical-engineering expansion. These presets intentionally use each
    # employer's own careers surface; the track filter later keeps Israel/EE roles.
    "valens": {"url": "https://www.valens.com/positions/", "selector": 'a[href*="/position/"]', "id_pattern": r"/position/([^/?#]+)/?", "company": "Valens Semiconductor", "prefer_link_text": True, "http_first": True},
    "nextsilicon": {"url": "https://www.nextsilicon.com/careers/", "selector": 'a[href*="/careers/"]', "id_pattern": r"/careers/([^/?#]+)/?", "company": "NextSilicon", "prefer_link_text": True, "http_first": True, "hydrate_details": True, "hydrate_missing_title_only": True, "max_detail_jobs": 80},
    "retym": {"url": "https://retym.com/careers-2/", "selector": 'a[href*="/careers-2/"]', "id_pattern": r"/careers-2/(?:co/)?([^/?#]+)/?", "company": "Retym", "prefer_link_text": True, "http_first": True},
    "hailo": {"url": "https://hailo.ai/company-overview/careers/", "selector": 'a[href*="job"], a[href*="position"], a[href*="careers/"]', "id_pattern": r"(?:jobs?|positions?|careers)/([^/?#]+)", "company": "Hailo", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "pliops": {"url": "https://pliops.com/careers/", "selector": 'a[href*="job"], a[href*="position"], a[href*="careers/"]', "id_pattern": r"(?:jobs?|positions?|careers)/([^/?#]+)", "company": "Pliops", "prefer_link_text": True, "http_first": True, "static_only": True, "allow_empty": True, "allow_no_links": True},
    "chain-reaction": {"url": "https://chain-reaction.io/careers/", "selector": 'a[href*="/careers"]', "id_pattern": r"/careers(?:-2)?/(?:co/)?([^/?#]+)", "company": "Chain Reaction", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "scd": {"url": "https://scdusa-ir.com/find-a-job/", "selector": 'a[href*="job"], a[href*="position"]', "id_pattern": r"(?:jobs?|positions?)/([^/?#]+)", "company": "SCD - SemiConductor Devices", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "cadence": {"url": "https://cadence.wd1.myworkdayjobs.com/External_Careers", "selector": 'a[href*="/job/"]', "id_pattern": r"_([A-Za-z]\d+)$", "company": "Cadence Design Systems", "prefer_link_text": True, "selector_timeout_ms": 18000},
    "texas-instruments": {"url": "https://edbz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/jobs?location=Israel", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/([^/?#]+)", "company": "Texas Instruments", "prefer_link_text": True, "selector_timeout_ms": 18000, "dynamic_scroll": True},
    "flex-israel": {"url": "https://flex.com/careers/israel-en", "selector": 'a[href*="job"], a[href*="career"]', "id_pattern": r"(?:jobs?|careers?)/([^/?#]+)", "company": "Flex", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "siemens-eda": {"url": "https://www.siemens.com/en-us/company/jobs/", "selector": 'a[href*="jobs"], a[href*="careers"]', "id_pattern": r"(?:jobs?|careers?)/([^/?#]+)", "company": "Siemens EDA", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "marvell": {"url": "https://www.marvell.com/company/careers.html", "selector": 'a[href*="job"], a[href*="career"]', "id_pattern": r"(?:jobs?|careers?)[^/?#]*/([^/?#]+)", "company": "Marvell", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "broadcom-israel": {"url": "https://www.broadcom.com/company/careers", "selector": 'a[href*="job"], a[href*="career"]', "id_pattern": r"(?:jobs?|careers?)[^/?#]*/([^/?#]+)", "company": "Broadcom", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "synopsys-israel": {"url": "https://careers.synopsys.com/location/israel-jobs/44408/294640/2", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/([^/?#]+)", "company": "Synopsys", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "arm-israel": {"url": "https://careers.arm.com/location/israel-jobs/33099/294640/2", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/([^/?#]+)", "company": "Arm", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "dustphotonics": {"url": "https://www.dustphotonics.com/careers/", "selector": 'a[href*="career"], a[href*="job"], a[href*="position"]', "id_pattern": r"(?:careers?|jobs?|positions?)[^/?#]*/([^/?#]+)", "company": "DustPhotonics", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "wiliot": {"url": "https://www.wiliot.com/careers", "selector": 'a[href*="job"], a[href*="career"]', "id_pattern": r"(?:jobs?|careers?)[^/?#]*/([^/?#]+)", "company": "Wiliot", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "vayyar": {"url": "https://vayyar.com/recruitment/", "selector": 'a[href*="job"], a[href*="career"]', "id_pattern": r"(?:jobs?|careers?)[^/?#]*/([^/?#]+)", "company": "Vayyar Imaging", "prefer_link_text": True, "http_first": True, "allow_empty": True, "preserve_on_empty": True},
    "arbe": {"url": "https://arberobotics.com/careers/", "selector": 'a[href*="job"], a[href*="career"], a[href*="position"]', "id_pattern": r"(?:jobs?|careers?|positions?)[^/?#]*/([^/?#]+)", "company": "Arbe Robotics", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "trieye": {"url": "https://trieye.tech/careers/", "selector": 'a[href*="job"], a[href*="career"], a[href*="position"]', "id_pattern": r"(?:jobs?|careers?|positions?)[^/?#]*/([^/?#]+)", "company": "TriEye", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "speedata": {"url": "https://www.speedata.io/careers-1", "selector": 'a[href*="job"], a[href*="career"], a[href*="position"]', "id_pattern": r"(?:jobs?|careers?|positions?)[^/?#]*/([^/?#]+)", "company": "Speedata", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "proteantecs": {"url": "https://www.proteantecs.com/careers", "data_url": "https://www.comeet.co/careers-api/2.0/company/D5.00E/positions?token=5DE23340029121D562912029122334&details=false", "data_only": True, "trusted_israel_feed": True, "selector": 'a[href*="careerinfo"], a[href*="/careers/"]', "id_pattern": r"(?:careerinfo\?pi=|/careers/)([^&#/?]+)", "company": "proteanTecs", "prefer_link_text": True, "href_template": "https://www.proteantecs.com/careerinfo?pi={id}", "network_id_keys": ("uid", "pi", "positionId", "position_id", "jobId", "job_id", "id"), "network_id_pattern": r"[A-Za-z0-9][A-Za-z0-9.-]{2,40}", "network_title_keys": ("title", "name", "positionTitle", "jobTitle"), "network_description_keys": ("department", "employment_type", "experience_level", "workplace_type")},
    "innoviz": {"url": "https://innoviz.tech/join-us", "selector": 'a[href*="job"], a[href*="career"], a[href*="position"]', "id_pattern": r"(?:jobs?|careers?|positions?)[^/?#]*/([^/?#]+)", "company": "Innoviz", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "camtek": {"url": "https://www.camtek.com/careers/open-positions/", "selector": 'a[href*="/careers/open-positions/"]', "id_pattern": r"/open-positions/([^/?#]+)/?", "company": "Camtek", "prefer_link_text": True, "http_first": True, "hydrate_details": True, "hydrate_missing_title_only": True, "max_detail_jobs": 80},
    "nova": {"url": "https://www.novami.com/career", "selector": 'a[href*="job"], a[href*="career"], a[href*="position"]', "id_pattern": r"(?:jobs?|careers?|positions?)[^/?#]*/([^/?#]+)", "company": "Nova Measuring Instruments", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "neuroblade": {"url": "https://www.neuroblade.com/careers/", "selector": 'a[href*="gh_jid="], a[href*="/careers/"]', "id_pattern": r"(?:gh_jid=|/careers/)(\d+)", "company": "NeuroBlade", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "apple": {
        "url": "https://jobs.apple.com/en-il/search?location=israel-ISR",
        "selector": 'a[href*="/details/"]',
        "id_pattern": r"/details/([^/]+)/",
        "company": "Apple",
        "title_from_slug": True,
    },
    "amazon": {
        "url": "https://www.amazon.jobs/en/search?country=ISR&loc_query=Israel&result_limit=100",
        "selector": 'a[href*="/en/jobs/"]',
        "id_pattern": r"/jobs/(\d+)",
        "company": "Amazon",
        "title_from_slug": True,
    },
    "microsoft": {"url": "https://apply.careers.microsoft.com/careers?query=&location=Israel&domain=microsoft.com&sort_by=relevance", "selector": 'a[href*="/careers/job/"]', "id_pattern": r"/careers/job/(\d+)", "company": "Microsoft", "prefer_link_text": True, "settle_ms": 4500, "selector_timeout_ms": 25000, "dynamic_scroll": True},
    "mobileye": {"url": "https://careers.mobileye.com/jobs", "selector": 'a[href*="/jobs/"]', "id_pattern": r"/jobs/[^/]+/([^/?#]+)", "company": "Mobileye", "title_from_slug": True, "title_path_offset": -2},
    "checkpoint": {"url": "https://careers.checkpoint.com/index.php?a=search&fa%5B%5D=country_ss%3AIsrael&module=cpcareers&q=&sort=", "selector": 'a[href*="joborderid"], a[href*="a=show"], [onclick*="joborderid"]', "id_pattern": r"(?i)joborderid(?:=|%3D|[\"']?\s*:\s*[\"']?)(\d+)", "company": "Check Point", "http_first": True, "href_template": "https://careers.checkpoint.com/index.php?a=show&joborderid={id}&m=cpcareers", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 80, "capture_network": True, "text_id_pattern": r"(?i)Job\s*(?:ID|Id)\s*:\s*(\d+)", "sitemap_candidates": ("https://careers.checkpoint.com/sitemap.xml", "https://www.checkpoint.com/sitemap/"), "preserve_on_empty": True},
    "paloalto": {"url": "https://jobs.paloaltonetworks.com/en/location/israel-jobs/47263/294640/2", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/[^/]+/[^/]+/(\d+)", "company": "Palo Alto Networks"},
    "wix": {"url": "https://careers.wix.com/location/tel-aviv/positions", "selector": 'a[href*="/position/"], a[href*="/positions/"]', "id_pattern": r"/(?:position|positions)/([^/?#\s]+)", "company": "Wix", "load_more_text": "Load More Positions", "settle_ms": 3500, "selector_timeout_ms": 20000, "hydrate_details": True, "hydrate_missing_title_only": True, "max_detail_jobs": 120},
    "monday": {"url": "https://monday.com/careers", "selector": 'a[href*="/careers/"]', "id_pattern": r"/careers/([^/?#]+)(?:/|$)", "company": "monday.com", "prefer_link_text": True, "http_first": True, "hydrate_details": True, "hydrate_missing_title_only": True, "max_detail_jobs": 80},
    "cisco": {"url": "https://careers.cisco.com/global/en/search-results?keywords=&from=0&s=1&rk=l-israel", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/([^/?#]+)", "company": "Cisco"},
    "ibm": {"url": "https://www.ibm.com/careers/search?field_keyword_05[0]=Israel", "selector": 'a[href*="/careers/"][href*="job"]', "id_pattern": r"(?:job|jobs)[^A-Za-z0-9]+([A-Za-z0-9_-]{5,})", "company": "IBM", "allow_empty": True, "empty_markers": ("0 of 0 items", "1 – 0 of 0 items", "1 - 0 of 0 items", "0 jobs", "no jobs found", "no results")},
    "salesforce": {"url": "https://careers.salesforce.com/en/jobs/?search=&country=Israel", "selector": 'a[href*="/jobs/JR"], a[href*="/jobs/jr"], a[href*="/lavori/JR"], a[href*="/lavori/jr"], [data-href*="/jobs/JR"], [data-href*="/jobs/jr"], [data-url*="/jobs/JR"], [data-url*="/jobs/jr"]', "id_pattern": r"(?i)/(?:jobs|lavori)/(jr\d+)(?:/|$)", "company": "Salesforce", "title_from_slug": True, "settle_ms": 4500, "selector_timeout_ms": 25000, "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 80, "dynamic_scroll": True, "capture_network": True, "href_template": "https://careers.salesforce.com/en/jobs/{id}/", "text_id_pattern": r"(?i)\b(JR\d{5,})\b", "sitemap_candidates": ("https://careers.salesforce.com/sitemap.xml",), "preserve_on_empty": True},
    "meta": {"url": "https://www.metacareers.com/jobs?offices[0]=Tel%20Aviv%2C%20Israel", "selector": 'a[href*="/jobs/"]', "id_pattern": r"/jobs/(\d{10,})/?", "company": "Meta", "prefer_link_text": True, "settle_ms": 4000, "selector_timeout_ms": 22000, "dynamic_scroll": True, "preserve_on_empty": True},
    "qualcomm": {"url": "https://careers.qualcomm.com/careers?location=Israel", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/([^/?#]+)", "company": "Qualcomm"},
    "samsung": {"url": "https://research.samsung.com/sril/careers", "selector": 'a[href*="career"], a[href*="job"]', "id_pattern": r"(?:job|career)[^0-9]*([A-Za-z0-9_-]{4,})", "company": "Samsung Research Israel"},
    "applied-materials": {"url": "https://amat.wd1.myworkdayjobs.com/External", "selector": 'a[href*="/job/"]', "id_pattern": r"_([A-Z]\d+)$", "company": "Applied Materials"},
    "philips": {"url": "https://www.careers.philips.com/il/en/search-results", "selector": 'a[href*="/il/en/job/"]', "id_pattern": r"/job/(\d+)/", "company": "Philips"},
    "elbit": {"url": "https://elbitsystemscareer.com/jobs/", "data_url": "https://elbitsystemscareer.com/cron/jobs.json", "data_only": True, "trusted_israel_feed": True, "selector": 'a[href*="/job/"], a[href*="jid="], [data-href*="/job/"], [data-href*="jid="], [data-url*="/job/"], [data-url*="jid="], [onclick*="jid="]', "id_pattern": r"(?i)(?:/job/(?:[^/?#]+/)?|[?&]jid=/?|[\"']jid[\"']\s*:\s*[\"']?)(\d+)", "company": "Elbit Systems", "prefer_link_text": True, "href_template": "https://elbitsystemscareer.com/job/?jid={id}", "raw_id_fallback": True, "capture_network": True, "sitemap_candidates": ("https://elbitsystemscareer.com/sitemap.xml",), "network_id_keys": ("jid", "jobId", "job_id", "requisitionId", "id"), "network_id_pattern": r"\d{3,10}", "network_title_keys": ("title", "jobTitle", "job_title", "name"), "network_location_keys": ("location", "locationAddress", "city", "site"), "network_description_keys": ("description", "requirements", "skills")},
    "rafael": {"url": "https://career.rafael.co.il/search/", "trusted_israel_feed": True, "selector": 'a[href*="/job/"], a[href*="jobid="], [data-href*="/job/"], [data-url*="/job/"], [onclick*="/job/"]', "id_pattern": r"(?:/job/(?:[^/?#]+/)?|[?&]jobid=|[?&]jp_job=)([A-Za-z0-9-]+)", "dom_card_fallback": True, "company": "Rafael", "http_first": True, "selector_timeout_ms": 18000, "settle_ms": 1800, "challenge_wait_rounds": 8, "prefer_link_text": True, "href_template": "https://career.rafael.co.il/job/{id}/", "raw_id_fallback": True, "hydrate_details": True, "hydrate_missing_title_only": True, "max_detail_jobs": 180, "dynamic_scroll": True, "capture_network": True, "text_id_pattern": r"(?:מס(?:פר|['׳])?\s*משרה|job\s*(?:id|number))\s*[:#-]?\s*(\d{4,8})", "sitemap_candidates": ("https://career.rafael.co.il/wp-sitemap.xml", "https://career.rafael.co.il/sitemap_index.xml", "https://career.rafael.co.il/sitemap.xml"), "network_id_keys": ("jobId", "job_id", "jobNumber", "job_number", "id"), "network_id_pattern": r"\d{3,10}", "network_title_keys": ("title", "jobTitle", "job_title", "name")},
    "iai": {"url": "https://jobs.iai.co.il/jobs/", "data_url": "https://jobs.iai.co.il/wp-content/themes/tyco-wp/assets/json/jobs.json", "data_fallback_urls": ("https://r.jina.ai/http://jobs.iai.co.il/wp-content/themes/tyco-wp/assets/json/jobs.json",), "data_only": True, "trusted_israel_feed": True, "selector": 'a[href*="/job/"], [data-href*="/job/"], [data-url*="/job/"], [onclick*="/job/"]', "id_pattern": r"(?:/job/(?:[^/?#]+/)?|[?&]jp_job=)([A-Za-z0-9-]+)", "dom_card_fallback": True, "company": "Israel Aerospace Industries", "href_template": "https://jobs.iai.co.il/job/{id}/", "raw_id_fallback": True, "capture_network": True, "text_id_pattern": r"\[(76\d{6})\]", "sitemap_candidates": ("https://jobs.iai.co.il/sitemap.xml",), "network_id_keys": ("jobId", "job_id", "jobNumber", "job_number", "id"), "network_id_pattern": r"76\d{6}", "network_title_keys": ("title", "jobTitle", "job_title", "name", "tl"), "network_location_keys": ("location", "city", "site", "address", "jobLocation", "locationName", "ct"), "network_description_keys": ("description", "jobDescription", "dc", "jc", "tp")},
    "taboola": {"url": "https://www.taboola.com/careers/jobs", "selector": 'a[href*="/careers/job/"]', "id_pattern": r"/careers/job/([^/?#]+)", "company": "Taboola", "prefer_link_text": True},
    "appsflyer": {"url": "https://careers.appsflyer.com/herzliya/", "selector": 'a[href*="/jobs/position/"], [data-url*="/jobs/position/"], [onclick*="/jobs/position/"]', "id_pattern": r"/jobs/position/(\d+)/?", "company": "AppsFlyer", "http_first": True, "settle_ms": 3500, "selector_timeout_ms": 22000, "prefer_link_text": True, "href_template": "https://careers.appsflyer.com/jobs/position/{id}/", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 80},
    "similarweb": {"url": "https://www.similarweb.com/corp/careers/", "selector": 'a[href*="greenhouse.io/similarweb/jobs/"]', "id_pattern": r"/jobs/(\d+)", "company": "Similarweb"},
    "outbrain": {"url": "https://www.outbrain.com/careers/", "selector": 'a[href*="greenhouse.io/outbraininc/jobs/"]', "id_pattern": r"/jobs/(\d+)", "company": "Outbrain"},
    "cyberark": {"url": "https://www.cyberark.com/careers/all-job-openings/", "selector": 'a[href*="job_id="]', "id_pattern": r"job_id=([A-Za-z0-9_-]+)", "company": "CyberArk"},
    "cato": {"url": "https://www.catonetworks.com/careers/", "selector": 'a[href*="job"], a[href*="position"]', "id_pattern": r"(?:jobs?|positions?)/([^/?#]+)", "company": "Cato Networks"},
    "wiz": {"url": "https://www.wiz.io/careers", "selector": 'a[href*="job"], a[href*="position"]', "id_pattern": r"(?:jobs?|positions?)/([^/?#]+)", "company": "Wiz"},
    "orca": {"url": "https://orca.security/about/careers/", "selector": 'a[href*="/about/careers/"]', "id_pattern": r"/about/careers/(\d+)/", "company": "Orca Security"},
    "sentinelone": {"url": "https://www.sentinelone.com/jobs/?location=Israel", "selector": 'a[href*="job"]', "id_pattern": r"(?:jobs?|positions?)/([^/?#]+)", "company": "SentinelOne"},
    "aqua": {"url": "https://www.aquasec.com/about-us/careers/", "selector": 'a[href*="/about-us/careers/co/"]', "id_pattern": r"/careers/co/[^/]+/([^/]+)/", "company": "Aqua Security"},
}


class OfficialCareersCollector:
    """Reads verified, rendered official careers search pages."""

    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]:
        preset = PRESETS.get(identifier)
        if not preset:
            raise ValueError(f"Unsupported official careers preset: {identifier}")

        # Prefer a normal HTTP request for server-rendered boards. It is faster and
        # avoids Chromium/anti-bot timing issues. Dynamic boards fall back to
        # Playwright below when the static response contains no usable job links.
        rows: list[dict] = []
        if preset.get("data_url"):
            try:
                rows = await _collect_data_rows(preset)
            except PreserveExistingJobs:
                raise
            except Exception as exc:
                if preset.get("data_only"):
                    raise RuntimeError(f"Official jobs feed unavailable for {identifier}: {exc}") from exc
                rows = []
        if preset.get("http_first"):
            try:
                if not rows:
                    rows = await _collect_static_rows(preset)
                    rows = [row for row in rows if _resolve_row_href(row, preset)[1]]
            except Exception:
                rows = []

        rendered_error: Exception | None = None
        if not rows and not preset.get("data_only") and not preset.get("static_only"):
            try:
                rows = await self._collect_rendered_rows(identifier, preset)
            except Exception as exc:
                rendered_error = exc
                rows = []

        if not rows and preset.get("sitemap_candidates"):
            rows = await _collect_sitemap_rows(preset)

        if not rows and rendered_error is not None and (identifier == "rafael" or preset.get("preserve_on_empty")):
            raise PreserveExistingJobs(
                f"{preset['company']} temporarily blocked automated access; preserving the last successful job snapshot"
            ) from rendered_error
        if not rows and rendered_error is not None:
            raise rendered_error

        if preset.get("hydrate_details") and rows:
            rows = await _hydrate_detail_rows(rows, preset)

        results: dict[str, NormalizedJob] = {}
        for row in rows:
            href, match = _resolve_row_href(row, preset)
            if not match:
                continue
            text = " ".join(str(row.get("text") or "").split())
            title = _resolve_title(
                row,
                href,
                bool(preset.get("title_from_slug")),
                path_offset=int(preset.get("title_path_offset", -1)),
                prefer_link_text=bool(preset.get("prefer_link_text")),
            )
            title = _repair_known_listing_title(identifier, title, text)
            if not title:
                continue
            if identifier == "wix" and not _row_has_human_title({"title": title}):
                # Never persist Wix infrastructure IDs (oracle/seat/REF) as titles.
                # A later scan can recover the job once its detail page is readable.
                continue
            location = _extract_israel_location(text)
            if not location and preset.get("trusted_israel_feed"):
                location = "Israel"
            results[match.group(1)] = NormalizedJob(
                external_id=match.group(1), title=title, company=company_name or preset["company"],
                location=location, workplace="onsite", description=text,
                apply_url=href, source_url=href,
            )
        normalized = list(results.values())
        if not normalized and preset.get("preserve_on_empty"):
            raise PreserveExistingJobs(
                f"{preset['company']} did not expose a reliable job payload; preserving the last successful snapshot"
            ) from rendered_error
        return normalized

    async def _collect_rendered_rows(self, identifier: str, preset: dict) -> list[dict]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                context = await browser.new_context(
                    locale="en-US",
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9,he;q=0.8"},
                )
                page = await context.new_page()
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'platform', {get: () => 'Linux x86_64'});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en', 'he']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    window.chrome = window.chrome || {runtime: {}};
                    const originalQuery = navigator.permissions && navigator.permissions.query;
                    if (originalQuery) navigator.permissions.query = parameters =>
                      parameters.name === 'notifications'
                        ? Promise.resolve({state: Notification.permission})
                        : originalQuery.call(navigator.permissions, parameters);
                """)
                network_responses = []
                if preset.get("capture_network"):
                    def remember_response(response):
                        try:
                            resource_type = response.request.resource_type
                        except Exception:
                            resource_type = ""
                        if resource_type in {"document", "xhr", "fetch"} and len(network_responses) < 180:
                            network_responses.append(response)
                    page.on("response", remember_response)
                # Large career pages often keep analytics/ads open long after the jobs
                # themselves are usable. Waiting for DOMContentLoaded made healthy
                # sources such as Orca/IBM look broken. Commit first, then give the DOM
                # a short best-effort settle window.
                await page.goto(preset["url"], wait_until="commit", timeout=int(preset.get("goto_timeout_ms", 35_000)))
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=12_000)
                except Exception:  # page can still be fully usable for our selector
                    pass
                await page.wait_for_timeout(int(preset.get("settle_ms", 1400)))
                # Rafael currently fronts its public careers page with a JavaScript
                # browser challenge. Give a normal browser a bounded opportunity to
                # complete the redirect before inspecting the actual jobs DOM.
                for _ in range(int(preset.get("challenge_wait_rounds", 0))):
                    content = await page.content()
                    if "kramericaindustries" not in content and "window.rbzns" not in content:
                        break
                    await page.wait_for_timeout(1_000)

                load_more_text = str(preset.get("load_more_text") or "").strip()
                if load_more_text:
                    for _ in range(12):
                        button = page.get_by_text(load_more_text, exact=True).last
                        try:
                            if not await button.is_visible(timeout=600):
                                break
                            await button.click(timeout=2_000)
                            await page.wait_for_timeout(450)
                        except Exception:
                            break

                if preset.get("dynamic_scroll"):
                    for fraction in (0.25, 0.5, 0.75, 1.0):
                        await page.evaluate(
                            "(fraction) => window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) * fraction)",
                            fraction,
                        )
                        await page.wait_for_timeout(550)
                    await page.evaluate("window.scrollTo(0, 0)")
                    await page.wait_for_timeout(350)
                links = page.locator(preset["selector"])
                try:
                    await links.first.wait_for(state="attached", timeout=int(preset.get("selector_timeout_ms", 12_000)))
                except Exception as exc:
                    try:
                        body_text = " ".join((await page.locator("body").inner_text(timeout=3_000)).split())
                    except Exception:
                        body_text = ""
                    empty_markers = tuple(str(marker).casefold() for marker in preset.get("empty_markers", ()))
                    if preset.get("allow_empty") and any(marker in body_text.casefold() for marker in empty_markers):
                        return []
                    generic_rows = await page.locator("a[href], [onclick], [data-href], [data-url]").evaluate_all(
                        """els => els.map(a => {
                          let container = a;
                          let node = a;
                          for (let i = 0; i < 6 && node && node.parentElement; i++) {
                            const parent = node.parentElement;
                            const clickable = parent.querySelectorAll('a[href], [onclick], [data-href], [data-url]').length;
                            if (clickable > 3) break;
                            container = parent;
                            node = parent;
                          }
                          const heading = container.querySelector('h1,h2,h3,h4,[role="heading"]');
                          return {
                            href: a.getAttribute('href') || '',
                            onclick: a.getAttribute('onclick') || '',
                            title: heading ? (heading.innerText || '').trim() : '',
                            linkText: (a.innerText || '').trim(),
                            text: (container.innerText || '').trim()
                          };
                        })"""
                    )
                    generic_rows = [row for row in generic_rows if _resolve_row_href(row, preset)[1]]
                    page_html = await page.content()
                    body_text = body_text or ""
                    raw_rows = _extract_raw_rows(page_html, preset) + _extract_text_id_rows(body_text, preset)
                    network_rows = await _collect_network_rows(network_responses, preset)
                    card_rows = []
                    if preset.get("dom_card_fallback"):
                        card_rows = await _collect_rendered_card_rows(page, preset)
                    if generic_rows or raw_rows or network_rows or card_rows:
                        return _dedupe_rows(generic_rows + raw_rows + network_rows + card_rows, preset)
                    if preset.get("allow_no_links"):
                        return []
                    raise RuntimeError(
                        f"No job links found for {identifier} at {preset['url']} using {preset['selector']}"
                    ) from exc
                rows = await links.evaluate_all(
                    """els => els.map(a => {
                      // Find the largest ancestor that belongs to this one job only.
                      // The old scraper used parentElement.parentElement, which on
                      // Taboola can be the whole jobs table. That made every job use
                      // the first title/location on the page.
                      const distinctJobLinks = node => new Set(els
                        .filter(candidate => node && node.contains(candidate))
                        .map(candidate => candidate.getAttribute('href') || candidate.getAttribute('onclick') || candidate.textContent)).size;
                      let container = a;
                      let node = a;
                      while (node && node.parentElement) {
                        const parent = node.parentElement;
                        // A card may contain both a linked title and an Apply button
                        // for the same role. Only stop climbing once an ancestor
                        // contains links to more than one distinct job.
                        if (distinctJobLinks(parent) > 1) break;
                        container = parent;
                        node = parent;
                      }
                      const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, [role="heading"]'))
                        .map(el => (el.innerText || '').trim())
                        .filter(Boolean);
                      return {
                        href: a.getAttribute('href') || '',
                        onclick: a.getAttribute('onclick') || '',
                        title: headings[0] || '',
                        linkText: (a.innerText || '').trim(),
                        text: (container.innerText || '').trim()
                      };
                    })"""
                )
                page_html = await page.content()
                body_text = ""
                try:
                    body_text = await page.locator("body").inner_text(timeout=3_000)
                except Exception:
                    pass
                network_rows = await _collect_network_rows(network_responses, preset)
                rows = _dedupe_rows(
                    rows + _extract_raw_rows(page_html, preset) + _extract_text_id_rows(body_text, preset) + network_rows,
                    preset,
                )
            finally:
                await browser.close()
        return rows


async def _collect_rendered_card_rows(page, preset: dict) -> list[dict]:
    """Recover jobs from rendered listing cards when the site exposes no job hrefs.

    IAI and Rafael render useful job content but can keep the actual navigation in
    framework event handlers/state.  Treat each substantial heading/card as a job
    and use a deterministic listing URL token for JobPilot identity.  Clicking the
    result still lands on the employer's official jobs page rather than a guessed
    detail URL.
    """
    raw = await page.locator("h2, h3, h4, [role=heading]").evaluate_all(
        """els => els.map(h => {
          const title = (h.innerText || '').trim();
          let node = h;
          let best = h;
          for (let i = 0; i < 7 && node && node.parentElement; i++) {
            const parent = node.parentElement;
            const text = (parent.innerText || '').trim();
            if (text.length > 40 && text.length < 7000) best = parent;
            if (text.length >= 7000) break;
            node = parent;
          }
          return {title, text: (best.innerText || '').trim()};
        })"""
    )
    ignored = {
        "משרות", "משרות פתוחות", "לא נמצאו משרות פתוחות", "תחומי עיסוק",
        "חיפוש משרות", "jobs", "open positions", "careers",
    }
    rows: list[dict] = []
    seen: set[str] = set()
    base = str(preset["url"])
    sep = "&" if "?" in base else "?"
    for item in raw:
        title = " ".join(str(item.get("title") or "").split()).strip()
        text = " ".join(str(item.get("text") or "").split()).strip()
        if not title or title.casefold() in {x.casefold() for x in ignored}:
            continue
        if len(title) < 3 or len(title) > 180 or len(text) < max(35, len(title) + 12):
            continue
        # Avoid navigation/footer headings and repeated parent containers.
        normalized = title.casefold()
        if normalized in seen:
            continue
        job_signals = ("תפקיד", "דרוש", "מחפשים", "משרה", "ניסיון", "מהנדס", "מהנדסת",
                       "engineer", "developer", "manager", "student", "fpga", "vlsi")
        if not any(signal in text.casefold() for signal in job_signals):
            continue
        seen.add(normalized)
        stable = hashlib.sha256((title + "\n" + text[:800]).encode("utf-8")).hexdigest()[:16]
        rows.append({
            "href": f"{base}{sep}jp_job={stable}", "onclick": "",
            "title": title, "linkText": title, "text": text,
        })
    return rows


async def _collect_sitemap_rows(preset: dict) -> list[dict]:
    """Discover official detail URLs from sitemap indexes when the jobs UI is JS-only.

    This is intentionally restricted to fixed, preset-owned sitemap URLs. It never
    follows arbitrary URLs supplied by a user.
    """
    queue = [(str(url), 0) for url in preset.get("sitemap_candidates", ())]
    seen: set[str] = set()
    rows: list[dict] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; JobPilot/0.3; +official-careers-discovery)",
        "Accept": "application/xml,text/xml,text/html;q=0.9,*/*;q=0.5",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=12.0, headers=headers) as client:
        while queue and len(seen) < 36 and len(rows) < int(preset.get("max_detail_jobs", 100)) * 3:
            url, depth = queue.pop(0)
            if url in seen or depth > 2:
                continue
            seen.add(url)
            try:
                response = await client.get(url)
                if response.status_code >= 400 or len(response.content) > 12_000_000:
                    continue
                raw = response.text
            except Exception:
                continue
            locations: list[str] = []
            try:
                root = ET.fromstring(raw)
                locations = [str(node.text or "").strip() for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "loc"]
            except Exception:
                soup = BeautifulSoup(raw, "html.parser")
                locations = [node.get_text(strip=True) for node in soup.select("loc")]
            for location in locations:
                if not location:
                    continue
                if location.lower().split("?", 1)[0].endswith(".xml"):
                    if depth < 2:
                        queue.append((location, depth + 1))
                    continue
                row = {"href": location, "onclick": "", "title": "", "linkText": "", "text": ""}
                if _resolve_row_href(row, preset)[1]:
                    rows.append(row)
    return _dedupe_rows(rows, preset)


async def _collect_network_rows(responses: list, preset: dict) -> list[dict]:
    """Recover jobs from XHR/fetch payloads used by dynamic careers boards."""
    if not responses:
        return []
    rows: list[dict] = []
    for response in responses[-180:]:
        try:
            content_type = str(response.headers.get("content-type") or "").casefold()
            if content_type and not any(token in content_type for token in ("json", "html", "text", "javascript")):
                continue
            body = await response.text()
        except Exception:
            continue
        if not body or len(body) > 8_000_000:
            continue
        rows.extend(_extract_raw_rows(body, preset))
        rows.extend(_extract_text_id_rows(body, preset))
        rows.extend(_extract_structured_job_rows(body, preset))
    return _dedupe_rows(rows, preset)


async def _collect_data_rows(preset: dict) -> list[dict]:
    """Read a preset-owned public jobs feed before attempting browser scraping."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.5",
        "Referer": str(preset["url"]),
    }
    endpoints = [str(preset["data_url"]), *(str(url) for url in preset.get("data_fallback_urls", ()))]
    response = None
    rows: list[dict] = []
    route = "direct"
    async with httpx.AsyncClient(follow_redirects=True, timeout=75.0, headers=headers) as client:
        for index, endpoint in enumerate(endpoints):
            response = await client.get(endpoint)
            if len(response.content) > 16_000_000:
                raise RuntimeError("Official jobs feed exceeded the safe size limit")
            payload = response.text
            if index:
                wrapped = re.search(r"(?s)Markdown Content:\s*(\[.*)", payload)
                if wrapped:
                    payload = wrapped.group(1)
            rows = _extract_structured_job_rows(payload, preset)
            route = "direct" if index == 0 else f"fallback-{index}"
            if rows:
                break
            if response.status_code >= 400 and index == len(endpoints) - 1:
                response.raise_for_status()
    if preset.get("data_only"):
        print(
            f"[collector-feed] company={preset.get('company')} status={response.status_code} "
            f"bytes={len(response.content)} rows={len(rows)} route={route} "
            f"content_type={response.headers.get('content-type', '')[:80]}",
            flush=True,
        )
        if not rows:
            raise PreserveExistingJobs(
                f"{preset.get('company')} returned an empty or unrecognized official jobs feed"
            )
    return rows


def _extract_structured_job_rows(raw_payload: str, preset: dict) -> list[dict]:
    """Extract jobs from official JSON APIs that expose IDs but no detail links."""
    id_keys = tuple(preset.get("network_id_keys", ()))
    template = str(preset.get("href_template") or "")
    if not id_keys or not template:
        return []
    try:
        payload = json.loads(raw_payload)
    except Exception:
        return []
    title_keys = tuple(preset.get("network_title_keys", ("title", "jobTitle", "name")))
    location_keys = tuple(preset.get("network_location_keys", (
        "location", "city", "site", "address", "jobLocation", "locationName",
    )))
    description_keys = tuple(preset.get("network_description_keys", (
        "description", "jobDescription", "descriptionText",
    )))
    id_re = re.compile(str(preset.get("network_id_pattern") or r".{2,80}"))
    rows: list[dict] = []

    def scalar(value) -> str:
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return " ".join(str(value).split()).strip()
        if isinstance(value, dict):
            for key in ("name", "title", "label", "value", "city"):
                result = scalar(value.get(key)) if key in value else ""
                if result:
                    return result
        return ""

    def walk(node) -> None:
        if isinstance(node, dict):
            external_id = next((scalar(node.get(key)) for key in id_keys if scalar(node.get(key))), "")
            title = next((scalar(node.get(key)) for key in title_keys if scalar(node.get(key))), "")
            if external_id and title and id_re.fullmatch(external_id) and _row_has_human_title({"title": title}):
                location = next((scalar(node.get(key)) for key in location_keys if scalar(node.get(key))), "")
                text_parts = [title, location]
                for key in description_keys:
                    value_text = scalar(node.get(key)) if key in node else ""
                    if value_text:
                        text_parts.append(value_text)
                for key, value in node.items():
                    if key in id_keys or key in title_keys or key in location_keys or key in description_keys:
                        continue
                    value_text = scalar(value)
                    if value_text and len(value_text) <= 600:
                        text_parts.append(value_text)
                rows.append({
                    "href": template.format(id=external_id), "onclick": "",
                    "title": title, "linkText": title, "text": " ".join(text_parts)[:5000],
                })
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return _dedupe_rows(rows, preset)


def _extract_text_id_rows(raw_text: str, preset: dict) -> list[dict]:
    """Build canonical detail URLs from human-readable job IDs when links are absent."""
    pattern = str(preset.get("text_id_pattern") or "").strip()
    template = str(preset.get("href_template") or "").strip()
    if not pattern or not template:
        return []
    normalized = html_lib.unescape(str(raw_text or ""))
    rows: list[dict] = []
    for match in re.finditer(pattern, normalized):
        external_id = match.group(1)
        rows.append({
            "href": template.format(id=external_id),
            "onclick": "", "title": "", "linkText": "", "text": "",
        })
    return _dedupe_rows(rows, preset)


async def _collect_static_rows(preset: dict) -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers=headers) as client:
        response = await client.get(str(preset["url"]))
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    candidates = soup.select(str(preset["selector"]))
    if not candidates:
        # Selector drift is common on careers pages. The external-id regex is the
        # stronger contract, so fall back to any clickable element whose URL/action
        # still contains a valid job identifier.
        generic = soup.select("a[href], [onclick], [data-href], [data-url]")
        candidates = [element for element in generic if re.search(
            str(preset["id_pattern"]),
            " ".join((str(element.get("href") or ""), str(element.get("data-href") or ""), str(element.get("data-url") or ""), str(element.get("onclick") or ""))),
        )]
    rows: list[dict] = []
    for element in candidates:
        container = element
        node = element
        # Climb only while this ancestor still represents one role. This keeps title
        # and location bound to the correct job card instead of the whole board.
        for _ in range(7):
            parent = getattr(node, "parent", None)
            if parent is None or not hasattr(parent, "select"):
                break
            try:
                distinct = {
                    (candidate.get("href") or candidate.get("onclick") or candidate.get_text(" ", strip=True))
                    for candidate in parent.select(str(preset["selector"]))
                }
            except Exception:
                distinct = set()
            if len({value for value in distinct if value}) > 1:
                break
            container = parent
            node = parent
        heading = container.select_one("h1,h2,h3,h4,[role='heading']") if hasattr(container, "select_one") else None
        rows.append({
            "href": str(element.get("href") or ""),
            "dataHref": str(element.get("data-href") or ""),
            "dataUrl": str(element.get("data-url") or ""),
            "onclick": str(element.get("onclick") or ""),
            "title": heading.get_text(" ", strip=True) if heading else "",
            "linkText": element.get_text(" ", strip=True),
            "text": container.get_text(" ", strip=True),
        })
    return _dedupe_rows(rows + _extract_raw_rows(response.text, preset) + _extract_text_id_rows(BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True), preset), preset)


def _extract_raw_rows(raw_html: str, preset: dict) -> list[dict]:
    """Recover official job URLs/IDs from JSON/scripts when DOM selectors drift."""
    normalized = html_lib.unescape(str(raw_html or "")).replace("\\/", "/")
    pattern = re.compile(str(preset["id_pattern"]))
    rows: list[dict] = []
    for quoted in re.findall(r'''["']([^"']{1,1400})["']''', normalized):
        candidate = quoted.strip().replace("\\u0026", "&")
        if not pattern.search(candidate):
            continue
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        if candidate.startswith(("/", "http://", "https://")):
            rows.append({"href": candidate, "onclick": "", "title": "", "linkText": "", "text": ""})

    if preset.get("raw_id_fallback") and preset.get("href_template"):
        for match in pattern.finditer(normalized):
            rows.append({
                "href": str(preset["href_template"]).format(id=match.group(1)),
                "onclick": "", "title": "", "linkText": "", "text": "",
            })
    return _dedupe_rows(rows, preset)


def _dedupe_rows(rows: list[dict], preset: dict) -> list[dict]:
    unique: dict[str, dict] = {}
    for row in rows:
        href, match = _resolve_row_href(row, preset)
        if not match:
            continue
        key = match.group(1).casefold()
        candidate = dict(row)
        candidate["href"] = href
        current = unique.get(key)
        score = int(bool(candidate.get("title") or candidate.get("linkText"))) * 3 + int(bool(candidate.get("text"))) * 2 + len(href) / 1000
        old_score = -1 if current is None else int(bool(current.get("title") or current.get("linkText"))) * 3 + int(bool(current.get("text"))) * 2 + len(str(current.get("href") or "")) / 1000
        if current is None or score > old_score:
            unique[key] = candidate
    return list(unique.values())


async def _hydrate_detail_rows(rows: list[dict], preset: dict) -> list[dict]:
    """Bind each external ID to its official detail title/location concurrently."""
    rows = _dedupe_rows(rows, preset)[: int(preset.get("max_detail_jobs", 80))]
    semaphore = asyncio.Semaphore(8)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/150 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0, headers=headers) as client:
        async def one(row: dict) -> dict:
            href, match = _resolve_row_href(row, preset)
            if not href or not match:
                return row
            if preset.get("hydrate_missing_title_only") and _row_has_human_title(row):
                return row
            try:
                async with semaphore:
                    response = await client.get(href)
                if response.status_code >= 400:
                    return row
                soup = BeautifulSoup(response.text, "html.parser")
                heading = soup.select_one("h1, main h2, article h2, [role='main'] h2")
                title = heading.get_text(" ", strip=True) if heading else ""
                body = soup.select_one("main, article, [role='main']") or soup.body
                text = body.get_text(" ", strip=True) if body else ""
                canonical = soup.select_one('link[rel="canonical"]')
                canonical_href = str(canonical.get("href") or "") if canonical else ""
                result = dict(row)
                result.update({
                    "href": canonical_href or str(response.url),
                    "title": title or row.get("title") or "",
                    "linkText": title or row.get("linkText") or "",
                    "text": text or row.get("text") or "",
                })
                return result
            except Exception:
                return row
        return await asyncio.gather(*(one(row) for row in rows))


def _resolve_row_href(row: dict, preset: dict) -> tuple[str, re.Match[str] | None]:
    raw_href = str(row.get("href") or "").strip()
    data_href = str(row.get("dataHref") or row.get("data-href") or "").strip()
    data_url = str(row.get("dataUrl") or row.get("data-url") or "").strip()
    onclick = str(row.get("onclick") or "").strip()
    base_url = str(preset["url"])
    raw_target = raw_href or data_href or data_url
    href = urljoin(base_url, raw_target) if raw_target else ""
    searchable = " ".join(part for part in (href, raw_href, data_href, data_url, onclick) if part)
    match = re.search(str(preset["id_pattern"]), searchable)
    if match and (not href or not re.search(str(preset["id_pattern"]), href)):
        template = str(preset.get("href_template") or "")
        if template:
            href = template.format(id=match.group(1))
    return href, match


GENERIC_LINK_TITLES = {
    "see full role description", "read more", "read more >", "more info", "more info >",
    "...read more", "…read more", "view job", "job details", "learn more", "apply", "apply now",
}


def _row_has_human_title(row: dict) -> bool:
    """Return True only when the listing already exposes a meaningful job title."""
    for raw in (row.get("title"), row.get("linkText")):
        candidate = " ".join(str(raw or "").split()).strip()
        if not candidate:
            continue
        normalized = candidate.casefold().strip(" .…→-")
        if normalized in {value.strip(" .…→-") for value in GENERIC_LINK_TITLES}:
            continue
        # Wix Oracle/seat identifiers are implementation IDs, not job titles.
        # Accept both raw slug form and the title-cased form produced by old code.
        identifierish = re.sub(r"\s+", "-", candidate.strip())
        if re.fullmatch(r"(?i)(?:oracle|seat)-[a-f0-9-]+(?:-t\d+)?-\d+", identifierish):
            continue
        if re.fullmatch(r"(?i)ref\d+[a-z]?", candidate):
            continue
        return True
    return False


def _resolve_title(
    row: dict,
    href: str,
    force_slug: bool = False,
    *,
    path_offset: int = -1,
    prefer_link_text: bool = False,
) -> str:
    """Prefer the stable job URL slug when a careers page exposes CTA text as the link label."""
    heading = " ".join(str(row.get("title") or "").split())
    raw_link_text = str(row.get("linkText") or "")
    if prefer_link_text:
        link_text = next((line.strip() for line in raw_link_text.splitlines() if line.strip()), "")
    else:
        link_text = " ".join(raw_link_text.split())
    candidate = link_text if prefer_link_text and link_text else heading or link_text
    normalized = candidate.casefold().strip(" .…→-")
    if force_slug or not candidate or normalized in {value.strip(" .…→-") for value in GENERIC_LINK_TITLES}:
        parts = [part for part in href.split("?", 1)[0].rstrip("/").split("/") if part]
        try:
            slug = parts[path_offset]
        except IndexError:
            slug = parts[-1] if parts else ""
        slug = re.sub(r"^(?:job|position)-", "", slug, flags=re.IGNORECASE)
        words = [word for word in slug.replace("_", "-").split("-") if word]
        keep_upper = {"ai", "ml", "qa", "ui", "ux", "hw", "fw", "cad", "dft", "pdv", "sre", "aws"}
        candidate = " ".join(word.upper() if word.casefold() in keep_upper else word.capitalize() for word in words)
    return candidate


def _repair_known_listing_title(identifier: str, title: str, text: str) -> str:
    """Recover titles from cards whose visible link contains only a CTA or ID."""
    compact = " ".join(str(text or "").split()).strip()
    if identifier == "texas-instruments":
        match = re.match(r"(.+?)\s+(?:Israel|Ra['’]anana, Israel)\s+POSTING DATE", compact, re.I)
        return match.group(1).strip() if match else title
    if identifier == "speedata":
        match = re.match(r"(.+?)\s+Israel\s+About the position", compact, re.I)
        return match.group(1).strip() if match else title
    if identifier == "camtek":
        if title.casefold() == "open positions":
            return ""
        if re.fullmatch(r"[A-Fa-f0-9]{2,3}[.-][A-Fa-f0-9]{3}", title):
            match = re.match(
                r"(.+?)\s+(?:R&D|Marketing|Operations|Engineering|Product|Applications?)\s+Migdal",
                compact, re.I,
            )
            return match.group(1).strip() if match else ""
    if identifier in {"samsung", "sentinelone"} and title.strip() in {"SNS", "\\"}:
        return ""
    return title

_ISRAEL_CITY_NAMES = (
    "Tel Aviv", "Tel Aviv-Yafo", "Haifa", "Herzliya", "Jerusalem", "Ramat Gan", "Petah Tikva",
    "Kiryat Gat", "Beer Sheva", "Be'er Sheva", "Yokneam", "Yoqneam", "Ra'anana",
    "Raanana", "Rehovot", "Netanya", "Caesarea", "Bnei Brak", "Rishon Lezion",
    "Kfar Saba", "Hod Hasharon", "Modiin", "Nes Ziona", "Or Yehuda", "Yehud",
    "Migdal Haemek", "Migdal Ha'Emek", "Ramat-Gan", "Tel Aviv-Yafo",
)

_HEBREW_ISRAEL_LOCATIONS = {
    "תל אביב": "Tel Aviv, Israel", "תל אביב-יפו": "Tel Aviv, Israel", "תל אביב יפו": "Tel Aviv, Israel",
    "חיפה": "Haifa, Israel", "הרצליה": "Herzliya, Israel", "ירושלים": "Jerusalem, Israel",
    "רמת גן": "Ramat Gan, Israel", "פתח תקווה": "Petah Tikva, Israel", "פתח תקוה": "Petah Tikva, Israel",
    "קריית גת": "Kiryat Gat, Israel", "קרית גת": "Kiryat Gat, Israel", "באר שבע": "Be'er Sheva, Israel",
    "יקנעם": "Yokneam, Israel", "יוקנעם": "Yokneam, Israel", "רחובות": "Rehovot, Israel",
    "נתניה": "Netanya, Israel", "קיסריה": "Caesarea, Israel", "בני ברק": "Bnei Brak, Israel",
    "ראשון לציון": "Rishon Lezion, Israel", "כפר סבא": "Kfar Saba, Israel", "הוד השרון": "Hod Hasharon, Israel",
    "מודיעין": "Modiin, Israel", "נס ציונה": "Nes Ziona, Israel", "אור יהודה": "Or Yehuda, Israel",
    "יהוד": "Yehud, Israel", "חולון": "Holon, Israel", "לוד": "Lod, Israel", "רמלה": "Ramla, Israel",
    "רמת השרון": "Ramat Hasharon, Israel", "ראש העין": "Rosh HaAyin, Israel", "גבעתיים": "Givatayim, Israel",
    "קריות": "Krayot, Israel", "גוש שגב": "Misgav, Israel",
}


def _extract_israel_location(text: str) -> str:
    """Return an Israeli location only when the individual job row proves it.

    Returning an empty string is intentional: scanner.py treats an unknown location
    as non-Israeli, which is much safer than the old fallback of labelling every
    unparsed role as ``Israel``.
    """
    compact = " ".join(str(text or "").split())
    for hebrew_name, canonical in _HEBREW_ISRAEL_LOCATIONS.items():
        if hebrew_name in compact:
            return canonical
    for city in _ISRAEL_CITY_NAMES:
        if re.search(rf"(?<![A-Za-z]){re.escape(city)}(?![A-Za-z])", compact, re.IGNORECASE):
            canonical = city.replace("Beer Sheva", "Be'er Sheva").replace("Raanana", "Ra'anana").replace("Yoqneam", "Yokneam")
            return f"{canonical}, Israel"
    # Several Israeli startup boards use ISO country codes instead of spelling out
    # the country (for example ``location_on IL`` or ``Tel Aviv · IL``). Require a
    # standalone token so words such as "skills" cannot create a false match.
    if re.search(r"(?<![A-Za-z])IL(?![A-Za-z])", compact):
        return "Israel"
    if re.search(r"(?<![A-Za-z])Israel(?![A-Za-z])", compact, re.IGNORECASE) or "ישראל" in compact:
        return "Israel"
    return ""
