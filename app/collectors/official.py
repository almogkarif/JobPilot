from __future__ import annotations

import asyncio
import html as html_lib
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .employer_details import employer_job_detail, employer_job_closed, matrix_job_rows
from .globale_detail import collect_globale_rows
from .matrix_detail import collect_matrix_rows
from .microsoft_detail import microsoft_position_detail
from .mobileye_detail import mobileye_job_detail, mobileye_job_closed
from .rafael_detail import is_rafael_access_challenge
from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import VERIFIED_ATS_IDENTIFIERS, collect_expansion_feed
from .eightfold import EIGHTFOLD_ROUTES, collect_eightfold
from .zim_ide import FEED_URLS as ZIM_IDE_FEEDS, collect_zim_ide
from .workday import EXPANSION_WORKDAY_IDENTIFIERS
from ..services.job_text import clean_job_text, job_text_quality
from ..services.source_quality import is_navigation_title
from ..source_expansion import EXPANDED_EMPLOYER_SOURCES


def _comeet_preset(company_slug: str, board_id: str, company: str) -> dict:
    """Preset for a public Comeet board whose job URLs are auto-routable."""
    base = f"https://www.comeet.com/jobs/{company_slug}/{board_id}"
    escaped_slug = re.escape(company_slug)
    escaped_board = re.escape(board_id)
    return {
        "url": base,
        "selector": f'a[href*="/jobs/{company_slug}/{board_id}/"]',
        "id_pattern": rf"/jobs/{escaped_slug}/{escaped_board}/[^/?#\s]+/([^/?#\s]+)",
        "company": company,
        "prefer_link_text": True,
        "http_first": True,
        "hydrate_details": True,
        "max_detail_jobs": 160,
        "preserve_on_empty": True,
        "network_id_keys": ("uid", "position_uid", "positionId", "id"),
        "network_id_pattern": r"[A-Za-z0-9][A-Za-z0-9.-]{2,40}",
        "network_title_keys": ("name", "title", "positionTitle", "jobTitle"),
        "network_location_keys": ("location", "locations", "city"),
        "network_description_keys": (
            "details", "custom_fields", "department", "employment_type", "experience_level", "workplace_type",
        ),
        "network_url_keys": (
            "url_comeet_hosted_page", "url_recruit_hosted_page", "url_active_page",
        ),
    }


PRESETS = {
    "g-stat": {"url": "https://g-stat.com/careers/", "company": "G-STAT", "http_first": True,
               "static_only": True, "trusted_israel_feed": True, "preserve_on_empty": True,
               "gstat_accordion": True, "selector": ".jobs_accordion > .row",
               "id_pattern": r"[?&]p=(\d+)", "max_inline_jobs": 100},
    # Electrical-engineering expansion. These presets intentionally use each
    # employer's own careers surface; the track filter later keeps Israel/EE roles.
    "valens": {"url": "https://www.valens.com/positions/", "selector": 'a[href*="/position/"]', "id_pattern": r"/position/([^/?#]+)/?", "company": "Valens Semiconductor", "prefer_link_text": True, "http_first": True},
    "nextsilicon": {"url": "https://www.nextsilicon.com/careers/", "selector": 'a[href*="/careers/"]', "id_pattern": r"/careers/([^/?#]+)/?", "company": "NextSilicon", "prefer_link_text": True, "http_first": True, "hydrate_details": True, "max_detail_jobs": 80},
    "retym": {"url": "https://retym.com/careers-2/", "selector": 'a.comeet-position[href]', "id_pattern": r"/careers-2/co/[^/?#]+/([A-Za-z0-9]{2,3}\.[A-Za-z0-9]{3})/", "company": "Retym", "prefer_link_text": True, "http_first": True},
    "hailo": {"url": "https://hailo.ai/company-overview/careers/", "selector": 'a[href*="job"], a[href*="position"], a[href*="careers/"]', "id_pattern": r"(?:jobs?|positions?|careers)/([^/?#]+)", "company": "Hailo", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "pliops": {"url": "https://pliops.com/careers/", "selector": 'a[href*="job"], a[href*="position"], a[href*="careers/"]', "id_pattern": r"(?:jobs?|positions?|careers)/([^/?#]+)", "company": "Pliops", "prefer_link_text": True, "http_first": True, "static_only": True, "allow_empty": True,
        "preserve_on_empty": True, "allow_no_links": True},
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
    "vayyar": {"url": "https://vayyar.com/recruitment/", "selector": 'a[href*="job"], a[href*="career"]', "id_pattern": r"(?:jobs?|careers?)[^/?#]*/([^/?#]+)", "company": "Vayyar Imaging", "prefer_link_text": True, "http_first": True, "allow_empty": True,
        "preserve_on_empty": True},
    "arbe": {"url": "https://arberobotics.com/career/", "selector": 'a[href*="/careers/"]', "id_pattern": r"/careers/([^/?#]+)/?", "company": "Arbe Robotics", "prefer_link_text": True, "http_first": True, "hydrate_details": True, "max_detail_jobs": 30, "preserve_on_empty": True},
    "trieye": {"url": "https://trieye.tech/careers/", "selector": 'a[href*="job"], a[href*="career"], a[href*="position"]', "id_pattern": r"(?:jobs?|careers?|positions?)[^/?#]*/([^/?#]+)", "company": "TriEye", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "speedata": {"url": "https://www.speedata.io/careers-1", "selector": 'a[href*="job"], a[href*="career"], a[href*="position"]', "id_pattern": r"(?:jobs?|careers?|positions?)[^/?#]*/([^/?#]+)", "company": "Speedata", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "proteantecs": {"url": "https://www.proteantecs.com/careers", "data_url": "https://www.comeet.co/careers-api/2.0/company/D5.00E/positions?token=5DE23340029121D562912029122334&details=true", "data_only": True, "trusted_israel_feed": True, "selector": 'a[href*="careerinfo"], a[href*="/careers/"]', "id_pattern": r"(?:careerinfo\?pi=|/careers/)([^&#/?]+)", "company": "proteanTecs", "prefer_link_text": True, "href_template": "https://www.proteantecs.com/careerinfo?pi={id}", "network_id_keys": ("uid", "pi", "positionId", "position_id", "jobId", "job_id", "id"), "network_id_pattern": r"[A-Za-z0-9][A-Za-z0-9.-]{2,40}", "network_title_keys": ("title", "name", "positionTitle", "jobTitle"), "network_description_keys": ("details", "description", "department", "employment_type", "experience_level", "workplace_type")},
    "innoviz": {"url": "https://innoviz.tech/join-us", "selector": 'a[href*="job"], a[href*="career"], a[href*="position"]', "id_pattern": r"(?:jobs?|careers?|positions?)[^/?#]*/([^/?#]+)", "company": "Innoviz", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "camtek": {"url": "https://www.camtek.com/careers/open-positions/", "selector": 'a[href*="/careers/open-positions/"]', "id_pattern": r"/open-positions/([^/?#]+)/?", "company": "Camtek", "prefer_link_text": True, "http_first": True, "hydrate_details": True, "max_detail_jobs": 80},
    "nova": {"url": "https://www.novami.com/career", "selector": 'a[href*="job"], a[href*="career"], a[href*="position"]', "id_pattern": r"(?:jobs?|careers?|positions?)[^/?#]*/([^/?#]+)", "company": "Nova Measuring Instruments", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "neuroblade": {"url": "https://www.neuroblade.com/careers/", "selector": 'a[href*="gh_jid="], a[href*="/careers/"]', "id_pattern": r"(?:gh_jid=|/careers/)(\d+)", "company": "NeuroBlade", "prefer_link_text": True, "http_first": True, "allow_empty": True},
    "apple": {
        "url": "https://jobs.apple.com/en-il/search?location=israel-ISR",
        "selector": 'a[href*="/details/"]',
        "id_pattern": r"/details/([^/]+)/",
        "company": "Apple",
        "title_from_slug": True,
        "hydrate_details": True,
        "max_detail_jobs": 160,
    },
    "amazon": {
        "url": "https://www.amazon.jobs/en/search?country=ISR&loc_query=Israel&result_limit=100",
        "selector": 'a[href*="/en/jobs/"]',
        "id_pattern": r"/jobs/(\d+)",
        "company": "Amazon",
        "title_from_slug": True,
        "hydrate_details": True,
        "max_detail_jobs": 160,
    },
    "microsoft": {"url": "https://apply.careers.microsoft.com/careers?query=&location=Israel&domain=microsoft.com&sort_by=relevance", "selector": 'a[href*="/careers/job/"]', "id_pattern": r"/careers/job/(\d+)", "company": "Microsoft", "prefer_link_text": True, "settle_ms": 4500, "selector_timeout_ms": 25000, "dynamic_scroll": True},
    "mobileye": {"url": "https://careers.mobileye.com/jobs", "selector": 'a[href*="/jobs/"]', "id_pattern": r"/jobs/[^/]+/([^/?#]+)", "company": "Mobileye", "title_from_slug": True, "title_path_offset": -2, "hydrate_details": True, "max_detail_jobs": 180},
    "checkpoint": {"url": "https://careers.checkpoint.com/index.php?a=search&fa%5B%5D=country_ss%3AIsrael&module=cpcareers&q=&sort=", "selector": 'a[href*="joborderid"], a[href*="a=show"], [onclick*="joborderid"]', "id_pattern": r"(?i)joborderid(?:=|%3D|[\"']?\s*:\s*[\"']?)(\d+)", "company": "Check Point", "http_first": True, "href_template": "https://careers.checkpoint.com/index.php?a=show&joborderid={id}&m=cpcareers", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 80, "capture_network": True, "text_id_pattern": r"(?i)Job\s*(?:ID|Id)\s*:\s*(\d+)", "sitemap_candidates": ("https://careers.checkpoint.com/sitemap.xml", "https://www.checkpoint.com/sitemap/"), "preserve_on_empty": True},
    "paloalto": {"url": "https://jobs.paloaltonetworks.com/en/location/israel-jobs/47263/294640/2", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/[^/]+/[^/]+/(\d+)", "company": "Palo Alto Networks", "hydrate_details": True, "max_detail_jobs": 120, "validate_detail_redirects": True, "detail_title_selector": ".section30__job-title", "detail_body_selector": ".section30__job-description"},
    "wix": {"url": "https://careers.wix.com/location/tel-aviv/positions", "selector": 'a[href*="/position/"], a[href*="/positions/"]', "id_pattern": r"/(?:position|positions)/([^/?#\s]+)", "company": "Wix", "load_more_text": "Load More Positions", "settle_ms": 3500, "selector_timeout_ms": 20000, "hydrate_details": True, "max_detail_jobs": 120},
    "monday": {"url": "https://monday.com/careers", "selector": 'a[href*="/careers/"]', "id_pattern": r"/careers/([^/?#]+)(?:/|$)", "company": "monday.com", "prefer_link_text": True, "http_first": True, "hydrate_details": True, "max_detail_jobs": 80, "location_from_detail_header": True},
    "cisco": {"url": "https://careers.cisco.com/global/en/search-results?keywords=&from=0&s=1&rk=l-israel", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/([^/?#]+)", "company": "Cisco", "hydrate_details": True, "max_detail_jobs": 120},
    "ibm": {"url": "https://www.ibm.com/careers/search?field_keyword_05[0]=Israel", "selector": 'a[href*="/careers/"][href*="job"]', "id_pattern": r"(?:job|jobs)[^A-Za-z0-9]+([A-Za-z0-9_-]{5,})", "company": "IBM", "allow_empty": True,
        "preserve_on_empty": True, "empty_markers": ("0 of 0 items", "1 – 0 of 0 items", "1 - 0 of 0 items", "0 jobs", "no jobs found", "no results")},
    # Salesforce can expose more than 1,500 global roles. Hydrating 80 detail
    # pages made the Israel source exceed the scanner's 45-second safety budget.
    # Listing cards already contain title/location, so keep hydration bounded.
    "salesforce": {"url": "https://careers.salesforce.com/en/jobs/?search=&country=Israel", "selector": 'a[href*="/jobs/JR"], a[href*="/jobs/jr"], a[href*="/lavori/JR"], a[href*="/lavori/jr"], [data-href*="/jobs/JR"], [data-href*="/jobs/jr"], [data-url*="/jobs/JR"], [data-url*="/jobs/jr"]', "id_pattern": r"(?i)/(?:jobs|lavori)/(jr\d+)(?:/|$)", "company": "Salesforce", "title_from_slug": True, "settle_ms": 2500, "selector_timeout_ms": 15000, "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 12, "dynamic_scroll": True, "capture_network": True, "href_template": "https://careers.salesforce.com/en/jobs/{id}/", "text_id_pattern": r"(?i)\b(JR\d{5,})\b", "sitemap_candidates": ("https://careers.salesforce.com/sitemap.xml",), "preserve_on_empty": True},
    "meta": {"url": "https://www.metacareers.com/jobs?offices[0]=Tel%20Aviv%2C%20Israel", "selector": 'a[href*="/jobs/"]', "id_pattern": r"/jobs/(\d{10,})/?", "company": "Meta", "prefer_link_text": True, "settle_ms": 4000, "selector_timeout_ms": 22000, "dynamic_scroll": True, "preserve_on_empty": True},
    "qualcomm": {"url": "https://careers.qualcomm.com/careers?location=Israel", "selector": 'a[href*="/job/"]', "id_pattern": r"/job/[^/]+/([^/?#]+)", "company": "Qualcomm"},
    "samsung": {"url": "https://research.samsung.com/sril/careers", "selector": 'a[href*="career"], a[href*="job"]', "id_pattern": r"(?:job|career)[^0-9]*([A-Za-z0-9_-]{4,})", "company": "Samsung Research Israel"},
    "applied-materials": {"url": "https://amat.wd1.myworkdayjobs.com/External", "selector": 'a[href*="/job/"]', "id_pattern": r"_([A-Z]\d+)$", "company": "Applied Materials"},
    "philips": {"url": "https://www.careers.philips.com/il/en/search-results", "selector": 'a[href*="/il/en/job/"]', "id_pattern": r"/job/(\d+)/", "company": "Philips"},
    "elbit": {"url": "https://elbitsystemscareer.com/jobs/", "data_url": "https://elbitsystemscareer.com/cron/jobs.json", "data_only": True, "trusted_israel_feed": True, "selector": 'a[href*="/job/"], a[href*="jid="], [data-href*="/job/"], [data-href*="jid="], [data-url*="/job/"], [data-url*="jid="], [onclick*="jid="]', "id_pattern": r"(?i)(?:/job/(?:[^/?#]+/)?|[?&]jid=/?|[\"']jid[\"']\s*:\s*[\"']?)(\d+)", "company": "Elbit Systems", "prefer_link_text": True, "href_template": "https://elbitsystemscareer.com/job/?jid={id}", "raw_id_fallback": True, "capture_network": True, "sitemap_candidates": ("https://elbitsystemscareer.com/sitemap.xml",), "network_id_keys": ("jid", "jobId", "job_id", "requisitionId", "id"), "network_id_pattern": r"\d{3,10}", "network_title_keys": ("title", "jobTitle", "job_title", "name"), "network_location_keys": ("location", "locationAddress", "city", "site"), "network_description_keys": ("description", "requirements", "skills")},
    "rafael": {"url": "https://career.rafael.co.il/search/", "external_fallback_url": "https://www.drushim.co.il/api/company/profile/?companycode=27381&companyname=%D7%A8%D7%A4%D7%90%D7%9C", "external_fallback_kind": "drushim_company", "external_fallback_before_browser": True, "trusted_israel_feed": True, "selector": 'a[href*="/job/"], a[href*="jobid="], [data-href*="/job/"], [data-url*="/job/"], [onclick*="/job/"]', "id_pattern": r"(?:/job/(?:[^/?#]+/)?|[?&]jobid=|[?&]jp_job=)([A-Za-z0-9-]+)", "dom_card_fallback": True, "company": "Rafael", "http_first": True, "selector_timeout_ms": 18000, "settle_ms": 1800, "challenge_wait_rounds": 8, "prefer_link_text": True, "href_template": "https://career.rafael.co.il/job/{id}/", "raw_id_fallback": True, "hydrate_details": True, "max_detail_jobs": 180, "dynamic_scroll": True, "capture_network": True, "text_id_pattern": r"(?:מס(?:פר|['׳])?\s*משרה|job\s*(?:id|number))\s*[:#-]?\s*(\d{4,8})", "sitemap_candidates": ("https://career.rafael.co.il/wp-sitemap.xml", "https://career.rafael.co.il/sitemap_index.xml", "https://career.rafael.co.il/sitemap.xml"), "network_id_keys": ("jobId", "job_id", "jobNumber", "job_number", "id"), "network_id_pattern": r"\d{3,10}", "network_title_keys": ("title", "jobTitle", "job_title", "name")},
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
    "aqua": {"url": "https://www.aquasec.com/about-us/careers/", "selector": 'a[href*="/about-us/careers/co/"]', "id_pattern": r"/careers/co/[^/]+/([^/]+)/", "company": "Aqua Security", "title_from_slug": True, "title_path_offset": -2},
    "claroty": {**_comeet_preset("Claroty", "F2.004", "Claroty"), "data_url": "https://www.comeet.co/careers-api/2.0/company/F2.004/positions?token=2F4EC42F42F45E814AC1A945E814AC5E8&details=true", "data_only": True},
    "vastdata": {**_comeet_preset("vastdata", "43.001", "VAST Data"), "data_url": "https://www.comeet.co/careers-api/2.0/company/43.001/positions?token=34110453411D4968234168209C31D49&details=true", "data_only": True},
    "gloat": {**_comeet_preset("gloat", "E5.000", "Gloat"), "data_url": "https://www.comeet.co/careers-api/2.0/company/E5.000/positions?token=5E02340002F0017800234011A01780&details=true", "data_only": True},
    "silverfort": {**_comeet_preset("silverfort", "54.007", "Silverfort"), "data_url": "https://www.comeet.co/careers-api/2.0/company/54.007/positions?token=45715B315B38AE22B8D051A0A457D051E61&details=true", "data_only": True},
    "4manalytics": _comeet_preset("4Manalytics", "B6.00F", "4M Analytics"),
    "exodigo": {**_comeet_preset("exodigo", "89.005", "Exodigo"), "data_url": "https://www.comeet.co/careers-api/2.0/company/89.005/positions?token=98542A398504C28391E130A391E391E2614&details=true", "data_only": True},
    "paragon": {**_comeet_preset("paragon", "76.006", "Paragon"), "data_url": "https://www.comeet.co/careers-api/2.0/company/76.006/positions?token=67626C46762D3A33B02D3A204E26C4676676&details=true", "data_only": True},
    "legitsecurity": {**_comeet_preset("legitsecurity.com", "37.004", "Legit Security"), "data_url": "https://www.comeet.co/careers-api/2.0/company/37.004/positions?token=7342B38159C159C40D41CD0073440D42404&details=true", "data_only": True},
    "voyantis": {
        **_comeet_preset("voyantis", "86.00B", "Voyantis"),
        "data_url": "https://www.comeet.co/careers-api/2.0/company/86.00B/positions?token=68B2742D1600D16020B71A2C2742&details=true",
        "data_only": True,
    },
    "sunflower": {"url": "https://www.comeet.com/jobs/sunflower/AA.009", "selector": 'a[href*="/jobs/sunflower/AA.009/"]', "id_pattern": r"/jobs/sunflower/AA\.009/[^/?#\s]+/([^/?#\s]+)", "company": "Sunflower", "prefer_link_text": True, "http_first": True, "hydrate_details": True, "max_detail_jobs": 120, "preserve_on_empty": True},
    "moonactive": {"url": "https://www.moonactive.com/careers/", "selector": 'a[href*="moonactive-position"], a[href*="/careers/"][href*="uid="]', "id_pattern": r"[?&]uid=([^&#\s]+)", "company": "Moon Active", "prefer_link_text": True, "http_first": True, "hydrate_details": True, "max_detail_jobs": 120, "dynamic_scroll": True, "preserve_on_empty": True},
    "connecteam": {"url": "https://connecteam.com/careers/", "selector": 'a[href*="/careers/"][href*="gh_jid="], a[href*="/careers/"]', "id_pattern": r"(?:[?&]gh_jid=|/careers/)(\d+)", "company": "Connecteam", "prefer_link_text": True, "http_first": True, "hydrate_details": True, "max_detail_jobs": 120, "preserve_on_empty": True},
}


def _bounded_official_board(url: str, company: str, *, trusted_israel_feed: bool = False) -> dict:
    """A cheap static-first adapter for smaller official employer boards.

    These sources deliberately avoid launching Chromium. If a board changes to a
    client-only shell, preserve the previous snapshot. Candidate links must expose
    a JobPosting schema before they may be treated as actual vacancies.
    """
    return {
        "url": url,
        "selector": 'a[href*="job"], a[href*="career"], a[href*="position"], a[href*="דרוש"]',
        "id_pattern": r"(?:jobs?|careers?|positions?|jobId|job_id)[^A-Za-z0-9]+([A-Za-z0-9][A-Za-z0-9._-]{2,80})",
        "company": company,
        "prefer_link_text": True,
        "http_first": True,
        "static_only": True,
        "allow_empty": True,
        "preserve_on_empty": True,
        "hydrate_details": True,
        "max_detail_jobs": 40,
        "require_job_schema": True,
        "trusted_israel_feed": trusted_israel_feed,
    }


PRESETS.update({
    item["identifier"]: _bounded_official_board(item["url"], item["company_name"])
    for item in EXPANDED_EMPLOYER_SOURCES
    if item["kind"] == "official_careers" and item["url"]
})

# These three sites expose stable Comeet boards.  Keep their official collector
# kind for compatibility with the application adapter, but parse the actual job
# cards instead of generic navigation links from the marketing careers page.
PRESETS.update({
    "cyera": _comeet_preset("cyera", "17.008", "Cyera"),
    "grip-security": _comeet_preset("grip", "A8.001", "Grip Security"),
    "reco": _comeet_preset("reco", "3A.00D", "Reco"),
})


# Additional official employers requested for the Industrial Engineering track.
# The adapters are intentionally bounded and shareable by CS/EE catalogs where
# the employer also publishes relevant technical roles.
PRESETS.update({
    "playtika": _bounded_official_board("https://www.playtika.com/careers/", "Playtika"),
    "fiverr": _bounded_official_board("https://www.fiverr.com/jobs", "Fiverr"),
    "ministry-of-defense-il": _bounded_official_board("https://www.mod.gov.il/Citizen_Service/Pages/jobs.aspx", "משרד הביטחון", trusted_israel_feed=True),
    "tower-semiconductor": _bounded_official_board("https://towersemi.com/careers/", "Tower Semiconductor"),
    "icl": _bounded_official_board("https://careers.icl-group.com/", "ICL"),
    "teva": {"url": "https://www.careers.teva/careers?location=Israel", "company": "Teva", "http_first": True, "static_only": True, "preserve_on_empty": True, "selector": 'a[href*="/careers/job/"]', "id_pattern": r"/careers/job/(\d+)", "embedded_positions": True, "hydrate_details": True, "max_detail_jobs": 40, "detail_api_template": "https://www.careers.teva/api/apply/v2/jobs/{id}?domain=tevapharm.com", "network_id_keys": ("id",), "network_title_keys": ("posting_name", "name"), "network_description_keys": ("job_description",), "network_url_keys": ("canonicalPositionUrl",)},
    "strauss": _bounded_official_board("https://www.strauss-group.com/career/", "Strauss Group", trusted_israel_feed=True),
    "osem-nestle": _bounded_official_board("https://www.osem-nestle.co.il/career", "Osem-Nestle", trusted_israel_feed=True),
    "cocacola-israel": _bounded_official_board("https://careers.cocacola.co.il/", "החברה המרכזית למשקאות", trusted_israel_feed=True),
    "fox-group": _bounded_official_board("https://www.foxhr.2.idus.co.il/", "Fox Group", trusted_israel_feed=True),
    "shufersal": _bounded_official_board("https://career.shufersal.co.il/", "Shufersal", trusted_israel_feed=True),
    "super-pharm": _bounded_official_board("https://jobs.super-pharm.co.il/careers/", "Super-Pharm", trusted_israel_feed=True),
    "deloitte-israel": _bounded_official_board("https://www.deloitte.com/il/en/careers.html", "Deloitte Israel"),
    "ey-israel": _bounded_official_board("https://www.ey.com/en_il/careers", "EY Israel"),
    "pwc-israel": _bounded_official_board("https://www.pwc.com/il/he/career.html", "PwC Israel"),
    "kpmg-israel": _bounded_official_board("https://kpmg.com/il/en/home/careers.html", "KPMG Israel"),
    "tefen": _bounded_official_board("https://www.tefen.com/careers/", "Tefen"),
    "niram-gitan": _bounded_official_board("https://www.niramgitan.com/", "Niram Gitan", trusted_israel_feed=True),
    "ness-israel": _bounded_official_board("https://www.ness-tech.co.il/careers", "Ness", trusted_israel_feed=True),
    "matrix-israel": _bounded_official_board("https://www.matrix.co.il/jobs/", "Matrix", trusted_israel_feed=True),
    "malam-team": _bounded_official_board("https://www.malamteam.com/careers/", "Malam Team", trusted_israel_feed=True),
    "one-technologies": {**_bounded_official_board("https://www.one1.co.il/careers/", "ONE Technologies", trusted_israel_feed=True), "inline_accordion": True, "id_pattern": r"[?&]share_job_id=(\d+)", "hydrate_details": False, "require_job_schema": False},
    "elad-systems": _bounded_official_board("https://www.eladsoft.com/careers/", "Elad Systems", trusted_israel_feed=True),
    "israel-post": _bounded_official_board("https://israelpost.co.il/%D7%90%D7%95%D7%93%D7%95%D7%AA/%D7%93%D7%A8%D7%95%D7%A9%D7%99%D7%9D/", "Israel Post", trusted_israel_feed=True),
    "ups-israel": _bounded_official_board("https://www.jobs-ups.com/", "UPS"),
    "dhl-israel": _bounded_official_board("https://careers.dhl.com/global/en", "DHL"),
    "israel-railways": _bounded_official_board("https://www.rail.co.il/?page=career", "Israel Railways", trusted_israel_feed=True),
    "ashdod-port": _bounded_official_board("https://www.ashdodport.co.il/about/careers/", "Ashdod Port", trusted_israel_feed=True),
    "haifa-port": _bounded_official_board("https://www.haifaport.co.il/jobs/", "Haifa Port", trusted_israel_feed=True),
    "friedenson": _bounded_official_board("https://fridenson.co.il/careers/", "Fridenson", trusted_israel_feed=True),
    "bank-leumi": _bounded_official_board("https://www.leumi.co.il/he/about-leumi/career", "Bank Leumi", trusted_israel_feed=True),
    "bank-hapoalim": _bounded_official_board("https://www.bankhapoalim.co.il/he/about/careers", "Bank Hapoalim", trusted_israel_feed=True),
    "discount-bank": _bounded_official_board("https://www.discountbank.co.il/private/general-information/careers/", "Israel Discount Bank", trusted_israel_feed=True),
    "cal": _bounded_official_board("https://www.cal-online.co.il/about/careers/", "Cal", trusted_israel_feed=True),
    "max": _bounded_official_board("https://www.max.co.il/careers", "Max", trusted_israel_feed=True),
    "isracard": _bounded_official_board("https://www.isracard.co.il/pages/careers/", "Isracard", trusted_israel_feed=True),
    "harel": _bounded_official_board("https://www.harel-group.co.il/about/harel-group/careers/Pages/default.aspx", "Harel", trusted_israel_feed=True),
    "phoenix": _bounded_official_board("https://www.fnx.co.il/about-us/careers/", "The Phoenix", trusted_israel_feed=True),
    "migdal": _bounded_official_board("https://www.migdal.co.il/about/careers", "Migdal", trusted_israel_feed=True),
    "clalit": _bounded_official_board("https://jobs.clalitapps.co.il/", "Clalit", trusted_israel_feed=True),
    "maccabi-health": _bounded_official_board("https://www.maccabi4u.co.il/careers/", "Maccabi Healthcare", trusted_israel_feed=True),
    "sheba": _bounded_official_board("https://www.sheba.co.il/%D7%93%D7%A8%D7%95%D7%A9%D7%99%D7%9D", "Sheba Medical Center", trusted_israel_feed=True),
    "ichilov": _bounded_official_board("https://www.tasmc.org.il/careers/", "Ichilov Medical Center", trusted_israel_feed=True),
})


# Verified detail adapters. Limits apply per explicit scan; failures preserve
# existing records rather than accepting summary cards as complete descriptions.
for _key, _limit in (('retym', 40), ('speedata', 40), ('microsoft', 80), ('texas-instruments', 40),
                     ('philips', 40), ('island', 40), ('mobileye', 180), ('rafael', 180)):
    PRESETS[_key].update(hydrate_details=True, max_detail_jobs=_limit,
                         require_complete_detail=True, detail_response_bytes=4_000_000)
PRESETS['retym'].update(listing_response_bytes=4_000_000, listing_canonical_on_detail=True)
PRESETS['speedata'].update(listing_card_location=True)
PRESETS['texas-instruments'].update(
    detail_api_template='https://edbz.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails/{id}',
    network_id_keys=('Id',), network_id_pattern=r'\d+', network_title_keys=('Title',),
    network_description_keys=('ExternalDescriptionStr', 'ExternalQualificationsStr'),
    network_location_keys=('PrimaryLocation',),
    href_template='https://edbz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/{id}/?location=Israel',
)
PRESETS['matrix-israel'].update(matrix_inline=True, max_inline_jobs=100,
    hydrate_details=False, selector='.job-item[job-id]', id_pattern=r'(?i)/(?:משרה|%D7%9E%D7%A9%D7%A8%D7%94)/([^/?#]+)')
PRESETS['global-e'].update(globale_feed=True, hydrate_details=False)
PRESETS['netafim'].update(
    url='https://careers.netafim.com/jobs', selector='a[href*="/jobs/"]',
    id_pattern=r'/jobs/(\d+)-', detail_response_bytes=4_000_000,
)

# These employer templates expose full vacancy sections without JobPosting JSON.
# Exact URL identities and bounded detail readers replace generic link guessing.
for _identifier, _overrides in {
    'priority-software': {'selector': 'a[href*="/careers/"]', 'id_pattern': r'/careers/([^/?#]+)/?$'},
    'stratasys': {'url': 'https://careers.stratasys.com/search/?q=&locationsearch=Israel',
                  'selector': 'a[href*="/job/"]', 'id_pattern': r'/job/[^/]+/(\d+)/?'},
    'mekorot': {'url': 'https://careers.mekorot.co.il/open-jobs/',
                'selector': 'a[href*="?job="]', 'id_pattern': r'[?&]job=([^&#]{1,240})(?:&|#|$)'},
    'electra-group': {'selector': 'a[href*="job_id="]', 'id_pattern': r'[?&]job_id=(\d+)',
                     'listing_canonical_on_detail': True},
}.items():
    PRESETS[_identifier].update(
        **_overrides, require_complete_detail=True, max_detail_jobs=40,
        detail_response_bytes=4_000_000, listing_response_bytes=4_000_000,
    )


class OfficialCareersCollector:
    """Reads verified, rendered official careers search pages."""

    async def collect(self, identifier: str, company_name: str = "") -> list[NormalizedJob]:
        if identifier in ZIM_IDE_FEEDS:
            return await collect_zim_ide(identifier, company_name)
        if identifier in EIGHTFOLD_ROUTES:
            return await collect_eightfold(identifier, company_name)
        if identifier in VERIFIED_ATS_IDENTIFIERS:
            return await collect_expansion_feed(identifier, company_name or PRESETS[identifier]["company"])
        if identifier in {"marvell", "broadcom-israel"} | EXPANSION_WORKDAY_IDENTIFIERS:
            from .workday import WorkdayCollector
            jobs = await WorkdayCollector().collect(identifier, company_name)
            # Keep legacy records until a separate, explicit reconciliation: the
            # previous generic adapter did not use these stable Workday IDs.
            return JobCollection(jobs, complete=False)
        preset = PRESETS.get(identifier)
        if not preset:
            raise ValueError(f"Unsupported official careers preset: {identifier}")

        # Prefer a normal HTTP request for server-rendered boards. It is faster and
        # avoids Chromium/anti-bot timing issues. Dynamic boards fall back to
        # Playwright below when the static response contains no usable job links.
        rows: list[dict] = []
        if preset.get("globale_feed"):
            rows = await collect_globale_rows()
        if preset.get("matrix_inline"):
            rows = await collect_matrix_rows(str(preset["url"]))
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
        external_fallback_attempted = False
        if not rows and preset.get("external_fallback_before_browser"):
            external_fallback_attempted = True
            try:
                rows = await _collect_external_fallback_rows(preset)
            except Exception as exc:
                rendered_error = exc
        if not rows and not preset.get("data_only") and not preset.get("static_only"):
            try:
                rows = await self._collect_rendered_rows(identifier, preset)
            except Exception as exc:
                rendered_error = exc
                rows = []

        if not rows and preset.get("sitemap_candidates"):
            rows = await _collect_sitemap_rows(preset)

        # Some employers block every data-center route to their official board.
        # A fixed, company-owned listing on a known Israeli job board is a safer
        # last resort than deleting the previous snapshot or inventing job URLs.
        # Keep the official site first and retain its canonical apply links.
        if not rows and preset.get("external_fallback_url") and not external_fallback_attempted:
            try:
                rows = await _collect_external_fallback_rows(preset)
            except Exception as exc:
                if rendered_error is None:
                    rendered_error = exc

        if not rows and rendered_error is not None and (identifier == "rafael" or preset.get("preserve_on_empty")):
            raise PreserveExistingJobs(
                f"{preset['company']} temporarily blocked automated access; preserving the last successful job snapshot"
            ) from rendered_error
        if not rows and rendered_error is not None:
            raise rendered_error

        if preset.get("hydrate_details") and rows:
            rows = await _hydrate_detail_rows(rows, preset)

        blocked_ids = tuple(str(row.get("_external_id") or match.group(1)) for row in rows if row.get("_detail_blocked")
                            and (match := _resolve_row_href(row, preset)[1]))
        results: dict[str, NormalizedJob] = {}
        for row in rows:
            if row.get("_detail_blocked"):
                continue
            if preset.get("require_complete_detail") and not ((row.get("_detail_complete") or row.get("_structured_description")) and job_text_quality(row.get("text")) == "complete"):
                continue
            if preset.get("require_job_schema") and not row.get("_verified_job"):
                continue
            href, match = _resolve_row_href(row, preset)
            if not match:
                continue
            text = clean_job_text(row.get("text"))
            title = _resolve_title(
                row,
                href,
                bool(preset.get("title_from_slug")),
                path_offset=int(preset.get("title_path_offset", -1)),
                prefer_link_text=bool(preset.get("prefer_link_text")),
            )
            title = _repair_known_listing_title(identifier, title, text)
            if not title or is_navigation_title(title):
                continue
            if identifier == "wix" and not _row_has_human_title({"title": title}):
                # Never persist Wix infrastructure IDs (oracle/seat/REF) as titles.
                # A later scan can recover the job once its detail page is readable.
                continue
            # monday's detail body mentions offices around the world. Its own
            # location is in the compact header, so do not let a later office
            # name turn a US/UK role into an Israeli role.
            location_text = text[:500] if preset.get("location_from_detail_header") else text
            explicit_location = str(row.get("location") or "")
            location = _extract_israel_location(explicit_location or location_text)
            if identifier == "elbit" and (not explicit_location or location == "Israel"):
                location = _elbit_hashtag_location(text) or location
            if not location and not explicit_location and preset.get("trusted_israel_feed"):
                location = "Israel"
            external_id = str(row.get("_external_id") or match.group(1))
            results[external_id] = NormalizedJob(
                external_id=external_id, title=title, company=company_name or preset["company"],
                location=location, workplace=_normalized_workplace(row.get("workplace")), description=text,
                apply_url=href, source_url=href,
                metadata={"verified_country_board": "g-stat.com"} if identifier == "g-stat" else {},
            )
        normalized = list(results.values())
        if not normalized:
            raise PreserveExistingJobs(
                f"{preset['company']} did not expose a reliable job payload; preserving the last successful snapshot",
                blocked_external_ids=blocked_ids
            ) from rendered_error
        return JobCollection(normalized, complete=False, blocked_external_ids=blocked_ids)

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


async def _collect_external_fallback_rows(preset: dict) -> list[dict]:
    """Read a bounded third-party mirror while preserving official apply URLs."""
    if preset.get("external_fallback_kind") != "drushim_company":
        return []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://www.drushim.co.il/",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=25.0, headers=headers) as client:
        response = await client.get(str(preset["external_fallback_url"]))
        response.raise_for_status()
    if len(response.content) > 8_000_000:
        raise RuntimeError("External jobs fallback exceeded the safe size limit")
    rows = _extract_drushim_company_rows(response.text, preset)
    print(
        f"[collector-fallback] company={preset.get('company')} provider=drushim "
        f"status={response.status_code} bytes={len(response.content)} rows={len(rows)}",
        flush=True,
    )
    return rows


def _extract_drushim_company_rows(raw_payload: str, preset: dict) -> list[dict]:
    """Convert Drushim's public company profile payload to canonical job rows."""
    try:
        payload = json.loads(raw_payload)
    except Exception:
        return []
    jobs = payload.get("Company", {}).get("Jobs", []) if isinstance(payload, dict) else []
    if not isinstance(jobs, list):
        return []
    rows: list[dict] = []
    for job in jobs[:250]:
        if not isinstance(job, dict):
            continue
        content = job.get("JobContent") if isinstance(job.get("JobContent"), dict) else {}
        send_model = job.get("SendCVButtonModel") if isinstance(job.get("SendCVButtonModel"), dict) else {}
        href = " ".join(str(send_model.get("ExternalLink") or "").split()).strip()
        # A small number of Drushim records concatenate the same external URL
        # twice. Keep only the first complete Rafael application URL.
        clean_href = re.match(
            r"(?i)(https?://[^\s?#]+/job\?jobid=[A-Za-z0-9-]+(?:&referid=\d+)?)",
            href,
        )
        if clean_href:
            href = clean_href.group(1)
        # Only accept links which resolve to this preset's canonical identifier.
        # Drushim's own job code is deliberately not used as Rafael's external ID.
        official_host = (urlparse(str(preset["url"])).hostname or "").casefold()
        fallback_host = (urlparse(href).hostname or "").casefold()
        if fallback_host != official_host or not _resolve_row_href({"href": href}, preset)[1]:
            continue
        title = " ".join(str(content.get("Name") or "").split()).strip()
        if not _row_has_human_title({"title": title}):
            continue
        addresses = content.get("Addresses") if isinstance(content.get("Addresses"), list) else []
        locations = [
            " ".join(str(item.get("City") or item.get("CityEnglish") or "").split()).strip()
            for item in addresses if isinstance(item, dict)
        ]
        locations = [value for value in locations if value]
        parts = [title, *locations]
        for key in ("Description", "Requirements"):
            value = content.get(key)
            if value:
                parts.append(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True))
        experience = content.get("Experience")
        if isinstance(experience, dict) and experience.get("NameInHebrew"):
            parts.append(str(experience["NameInHebrew"]))
        rows.append({
            "href": href, "onclick": "", "title": title, "linkText": title,
            "text": " ".join(parts)[:12000],
        })
    return _dedupe_rows(rows, preset)


def _extract_structured_job_rows(raw_payload: str, preset: dict) -> list[dict]:
    """Extract jobs from official JSON APIs that expose IDs but no detail links."""
    id_keys = tuple(preset.get("network_id_keys", ()))
    template = str(preset.get("href_template") or "")
    url_keys = tuple(preset.get("network_url_keys", ()))
    if not id_keys or not (template or url_keys):
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
            for key in ("city", "name", "title", "label", "value"):
                result = scalar(value.get(key)) if key in value else ""
                if result:
                    return result
        if isinstance(value, list):
            return ", ".join(part for item in value if (part := scalar(item)))
        return ""

    def rich_text(value) -> str:
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return clean_job_text(value)
        if isinstance(value, list):
            return clean_job_text("\n".join(rich_text(item) for item in value))
        if isinstance(value, dict):
            preferred = ("details", "text", "html", "value", "description", "requirements", "content", "label", "name", "title")
            parts = [rich_text(value[key]) for key in preferred if key in value]
            return clean_job_text("\n".join(part for part in parts if part))
        return ""

    def walk(node) -> None:
        if isinstance(node, dict):
            external_id = next((scalar(node.get(key)) for key in id_keys if scalar(node.get(key))), "")
            title = next((scalar(node.get(key)) for key in title_keys if scalar(node.get(key))), "")
            if external_id and title and id_re.fullmatch(external_id) and _row_has_human_title({"title": title}):
                href = next((scalar(node.get(key)) for key in url_keys if scalar(node.get(key))), "")
                if not href and template:
                    href = template.format(id=external_id)
                if not href:
                    return
                location = next((scalar(node.get(key)) for key in location_keys if scalar(node.get(key))), "")
                text_parts = [title, location]
                for key in description_keys:
                    value_text = rich_text(node.get(key)) if key in node else ""
                    if value_text:
                        text_parts.append(value_text)
                rows.append({
                    "href": href, "onclick": "",
                    "title": title, "linkText": title, "text": clean_job_text("\n".join(text_parts))[:12000],
                    "workplace": scalar(node.get("workplace_type")),
                    "location": location,
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


def _extract_one_job_rows(soup: BeautifulSoup) -> list[dict]:
    rows = []
    for card in soup.select("#company-job-opening .accordion_item[data-id]")[:200]:
        external_id = str(card.get("data-id") or "")
        heading = card.select_one(".job_title")
        content = card.select_one(".accordion_content")
        if not external_id.isdigit() or not heading or not content:
            continue
        title = heading.get_text(" ", strip=True)
        for footer in card.select(".accordion-footer"):
            footer.decompose()
        text = clean_job_text(str(card))
        rows.append({"href": f"https://www.one1.co.il/?share_job_id={external_id}",
                     "title": title, "linkText": title, "text": text})
    return rows


def _extract_gstat_job_rows(soup: BeautifulSoup, limit: int = 100) -> list[dict]:
    """G-STAT publishes complete descriptions and application forms inline."""
    rows = []
    seen = set()
    for card in soup.select(".jobs_accordion > .row")[:limit]:
        heading = card.select_one(".job-title[data-id]")
        job_id = str(heading.get("data-id") or "") if heading else ""
        if not job_id.isdigit() or job_id in seen:
            continue
        details = card.select_one(f"#job-data-{job_id}")
        form_id = details.select_one('input[name="job"]') if details else None
        if not form_id or str(form_id.get("value")) != job_id:
            continue
        description = "\n".join(column.get_text(" ", strip=True) for column in details.select(".job-inner-col.text-col"))
        title = heading.get_text(" ", strip=True)
        if not title or not description:
            continue
        target = ""
        for link in details.select(".share-div a[href]"):
            query = parse_qs(urlparse(link["href"]).query)
            candidate = next((query[key][0] for key in ("url", "u", "text") if query.get(key)), "")
            parsed = urlparse(candidate)
            if parsed.scheme == "https" and parsed.hostname == "g-stat.com" and parsed.path.startswith("/jobs/"):
                target = candidate
                break
        if not target:
            continue
        seen.add(job_id)
        rows.append({"href": target, "dataHref": f"https://g-stat.com/?p={job_id}", "title": title,
                     "text": description, "location": "Israel", "_structured_description": True})
    return rows


async def _collect_static_rows(preset: dict) -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers=headers) as client:
        response = await _bounded_detail_get(client, str(preset["url"]), preset.get("listing_response_bytes"))
        response.raise_for_status()
    # Comeet embeds complete job objects in the public HTML. Parse JSON data,
    # never execute the page's JavaScript or reduce it to Angular summary cards.
    if "comeet.com/jobs/" in str(preset["url"]):
        match = re.search(r"\bCOMPANY_POSITIONS_DATA\s*=\s*", response.text)
        if match:
            try:
                payload, _ = json.JSONDecoder().raw_decode(response.text[match.end():])
                structured = _extract_structured_job_rows(json.dumps(payload), preset)
                if structured:
                    return [{**row, "_structured_description": True} for row in structured]
            except (ValueError, TypeError):
                pass
    soup = BeautifulSoup(response.text, "html.parser")
    if preset.get("matrix_inline"):
        return matrix_job_rows(soup, str(preset["url"]), int(preset["max_inline_jobs"]))
    if preset.get("embedded_positions"):
        data = soup.select_one("#smartApplyData")
        if not data:
            return []
        try:
            payload = json.loads(data.get_text())
        except (ValueError, TypeError):
            return []
        return _extract_structured_job_rows(json.dumps(payload.get("positions") or []), preset)
    if preset.get("gstat_accordion"):
        return _extract_gstat_job_rows(soup, int(preset["max_inline_jobs"]))
    if preset.get("inline_accordion"):
        return _extract_one_job_rows(soup)
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
        card_location = ""
        if preset.get("listing_card_location"):
            card = element.find_parent(attrs={"role": "listitem"})
            # Speedata displays a dedicated country paragraph within each Wix card.
            # Never promote a footer address or another vacancy's location.
            if card and any(node.get_text(" ", strip=True).casefold() == "israel"
                            for node in card.select("p")):
                card_location = "Israel"
        rows.append({
            "location": card_location,
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


async def _bounded_detail_get(client, url: str, byte_limit: int | None):
    if not byte_limit:
        return await client.get(url)
    origin = urlparse(url).netloc
    for attempt in range(4):
        async with client.stream('GET', url, follow_redirects=False) as response:
            if response.is_redirect:
                target = urljoin(url, response.headers.get('location', ''))
                if attempt == 3 or urlparse(target).netloc != origin or urlparse(target).scheme != 'https':
                    raise ValueError('Employer detail redirect exceeded safe limits')
                # Close without downloading an unbounded intermediate body.
                url = target
                continue
            payload = bytearray()
            async for chunk in response.aiter_bytes():
                if len(payload) + len(chunk) > byte_limit:
                    raise ValueError('Employer detail response exceeded byte limit')
                payload.extend(chunk)
            return httpx.Response(response.status_code, content=bytes(payload), request=response.request)


async def _hydrate_detail_rows(rows: list[dict], preset: dict, *, retain_unavailable: bool = False) -> list[dict]:
    """Bind each external ID to its official detail title/location concurrently."""
    rows = _dedupe_rows(rows, preset)
    structured = [row for row in rows if row.get("_structured_description") and job_text_quality(row.get("text")) == "complete"]
    pending = [row for row in rows if not (row.get("_structured_description") and job_text_quality(row.get("text")) == "complete")]
    rows = structured + pending[: int(preset.get("max_detail_jobs", 80))]
    semaphore = asyncio.Semaphore(8)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/150 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0, headers=headers) as client:
        async def one(row: dict) -> dict:
            href, match = _resolve_row_href(row, preset)
            if not href or not match:
                return {**row, "_detail_status": "invalid_job_url"}
            if row.get("_structured_description") and job_text_quality(row.get("text")) == "complete":
                return row
            if preset.get("hydrate_missing_title_only") and _row_has_human_title(row):
                return row
            try:
                async with semaphore:
                    response = await _bounded_detail_get(client,
                        str(preset["detail_api_template"]).format(id=match.group(1))
                        if preset.get("detail_api_template") else href, preset.get("detail_response_bytes")
                    )
                if preset.get("company") == "Rafael" and is_rafael_access_challenge(response.status_code, response.text):
                    return {**row, "_detail_blocked": True, "_detail_status": "blocked", "_http_status": response.status_code}
                if response.status_code in {404, 410}:
                    return {**row, "_invalid_detail": True, "_detail_status": "unavailable", "_http_status": response.status_code}
                if response.status_code in {401, 403, 429}:
                    return {**row, "_detail_blocked": True, "_detail_status": "blocked", "_http_status": response.status_code}
                if response.status_code >= 400:
                    return {**row, "_detail_status": "http_error", "_http_status": response.status_code}
                if preset.get("company") == "Microsoft" and not _job_posting_detail(BeautifulSoup(response.text, "html.parser")):
                    api_url = ("https://apply.careers.microsoft.com/api/pcsx/position_details"
                               f"?position_id={match.group(1)}&domain=microsoft.com&hl=en")
                    async with semaphore:
                        api_response = await _bounded_detail_get(client, api_url, 4_000_000)
                    if api_response.status_code in {404, 410}:
                        return {**row, "_invalid_detail": True, "_detail_status": "unavailable",
                                "_http_status": api_response.status_code}
                    if api_response.status_code in {401, 403, 429}:
                        return {**row, "_detail_blocked": True, "_detail_status": "blocked",
                                "_http_status": api_response.status_code}
                    if api_response.status_code == 200:
                        detail = microsoft_position_detail(api_response.json(), match.group(1))
                        if detail:
                            if detail.pop("_availability_unverified"):
                                return {**row, **detail, "_detail_status": "availability_unverified",
                                        "_detail_blocked": True}
                            return {**row, **detail}
                if preset.get("detail_api_template"):
                    details = _extract_structured_job_rows(response.text, preset)
                    return next(({**detail, "href": href, "_detail_complete": True, "_verified_job": True}
                                 for detail in details if _resolve_row_href(detail, preset)[1]
                                 and _resolve_row_href(detail, preset)[1].group(1) == match.group(1)
                                 and job_text_quality(detail.get("text")) == "complete"), row)
                final_href = str(response.url)
                if preset.get("require_complete_detail"):
                    final_match = re.search(str(preset["id_pattern"]), final_href)
                    if not final_match or final_match.group(1) != match.group(1):
                        return row
                if preset.get("validate_detail_redirects") and not re.search(
                    str(preset["id_pattern"]), final_href,
                ):
                    # A successful redirect to the careers home page is the
                    # provider's tombstone for a role that no longer exists.
                    return {**row, "_invalid_detail": True, "_detail_status": "unavailable", "_http_status": response.status_code}
                soup = BeautifulSoup(response.text, "html.parser")
                if employer_job_closed(soup) or (preset.get("company") == "Mobileye" and mobileye_job_closed(soup)):
                    return {**row, "_invalid_detail": True, "_detail_status": "unavailable", "_http_status": response.status_code}
                heading = soup.select_one(str(preset.get("detail_title_selector") or "h1, main h2, article h2, [role='main'] h2"))
                title = heading.get_text(" ", strip=True) if heading else ""
                body_selector = str(preset.get("detail_body_selector") or "main, article, [role='main']")
                body = soup.select_one(body_selector) or soup.body
                text = clean_job_text(str(body)) if body else ""
                structured_detail = (mobileye_job_detail(soup) if preset.get("company") == "Mobileye" else None) or employer_job_detail(soup, str(preset.get("company")), external_id=match.group(1))
                if not structured_detail and preset.get("company") != "Retym":
                    structured_detail = _job_posting_detail(soup)
                if preset.get("require_complete_detail") and not structured_detail:
                    return row
                if structured_detail:
                    title, text, _ = structured_detail
                    if preset.get("require_complete_detail") and len(text) > 24000:
                        return row
                if preset.get("company") == "Apple":
                    text = _apple_embedded_detail_text(response.text) or text
                canonical = soup.select_one('link[rel="canonical"]')
                canonical_href = str(canonical.get("href") or "") if canonical else ""
                if preset.get("listing_canonical_on_detail") and canonical_href:
                    advertised, listing = urlparse(canonical_href), urlparse(str(preset['url']))
                    if (advertised.hostname == listing.hostname
                            and unquote(advertised.path).rstrip('/') == unquote(listing.path).rstrip('/')
                            and not advertised.query):
                        # Electra and Retym advertise the list URL as canonical.
                        # The final URL and employer-specific vacancy identity were both
                        # checked above; retain that exact vacancy URL.
                        canonical_href = ""
                # Branded Comeet pages sometimes return an unresolved client-side
                # shell.  Its canonical URL no longer matches the stable job route
                # and its heading still contains template placeholders.  Keep the
                # structured-feed values in that case instead of turning every job
                # into an unusable row during detail hydration.
                hydrated_href = canonical_href or final_href
                hydrated_match = re.search(str(preset["id_pattern"]), hydrated_href)
                if preset.get("require_complete_detail") and canonical_href and (not hydrated_match or unquote(hydrated_match.group(1)) != unquote(match.group(1))):
                    return row
                hydrated_title = title.strip()
                title_is_template = "{{" in hydrated_title or "}}" in hydrated_title
                result = dict(row)
                result["_verified_job"] = bool(structured_detail)
                result["_detail_complete"] = bool(structured_detail) and job_text_quality(text) == "complete"
                if structured_detail:
                    result["location"] = structured_detail[2] or row.get("location") or ""
                result.update({
                    "href": hydrated_href if hydrated_match else href,
                    "title": hydrated_title if hydrated_title and not title_is_template else row.get("title") or "",
                    "linkText": hydrated_title if hydrated_title and not title_is_template else row.get("linkText") or "",
                    "text": text if not title_is_template and job_text_quality(text) != "missing" and (result["_detail_complete"] or len(text) > len(str(row.get("text") or ""))) else row.get("text") or "",
                })
                return result
            except Exception as exc:
                return {**row, "_detail_status": "fetch_error", "_detail_error": type(exc).__name__}
        hydrated = await asyncio.gather(*(one(row) for row in rows))
        return hydrated if retain_unavailable else [row for row in hydrated if not row.get("_invalid_detail")]


def _job_posting_detail(soup: BeautifulSoup) -> tuple[str, str, str] | None:
    """Prefer the employer's JobPosting schema over page-wide marketing text."""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            candidates = node.get("@graph", [node])
            for candidate in candidates if isinstance(candidates, list) else []:
                if not isinstance(candidate, dict) or candidate.get("@type") != "JobPosting":
                    continue
                title = clean_job_text(candidate.get("title"))
                description = clean_job_text(candidate.get("description"))
                if not title or not description:
                    continue
                locations = candidate.get("jobLocation") or []
                if isinstance(locations, dict):
                    locations = [locations]
                addresses = []
                for location in locations:
                    address = location.get("address", {}) if isinstance(location, dict) else {}
                    if not isinstance(address, dict):
                        continue
                    for key in ("addressLocality", "addressRegion", "addressCountry"):
                        value = address.get(key)
                        if isinstance(value, dict):
                            value = value.get("name")
                        if isinstance(value, str):
                            addresses.append("Israel" if value.casefold() == "il" else value)
                return title, "\n".join([title, ", ".join(addresses), description]), ", ".join(addresses)
    return None


def _apple_embedded_detail_text(document: str) -> str:
    """Extract Apple's qualification JSON that is absent from the rendered shell."""
    match = re.search(r'JSON\.parse\(("(?:\\.|[^"\\])*")\)', str(document or ""))
    jobs_data: dict = {}
    if match:
        try:
            state = json.loads(json.loads(match.group(1)))
            queue = [state]
            while queue:
                node = queue.pop()
                if isinstance(node, dict):
                    candidate = node.get("jobsData")
                    if isinstance(candidate, dict):
                        jobs_data = candidate
                        break
                    queue.extend(node.values())
                elif isinstance(node, list):
                    queue.extend(node)
        except (TypeError, json.JSONDecodeError):
            jobs_data = {}

    fields = ("jobSummary", "description", "minimumQualifications", "preferredQualifications")
    parts = [str(jobs_data[field]) for field in fields if jobs_data.get(field)]
    locations = jobs_data.get("locations") or jobs_data.get("location") or []
    if isinstance(locations, dict):
        locations = [locations]
    if isinstance(locations, list):
        for location in locations:
            if not isinstance(location, dict):
                continue
            city = " ".join(str(location.get("city") or location.get("name") or "").split())
            country = " ".join(str(location.get("countryName") or "").split())
            if city:
                parts.append(", ".join(value for value in (city, country) if value))

    # Retain compatibility with older Apple pages that exposed isolated escaped
    # fields instead of one decodable router-state object.
    if not parts:
        for field in ("description", "minimumQualifications", "preferredQualifications"):
            legacy = re.search(rf'\\?"{field}\\?"\s*:\s*\\?"((?:\\\\.|[^"\\])*)', str(document or ""))
            if legacy:
                try:
                    parts.append(json.loads('"' + legacy.group(1) + '"'))
                except json.JSONDecodeError:
                    pass
    return clean_job_text("\n".join(parts)) if parts else ""


def _resolve_row_href(row: dict, preset: dict) -> tuple[str, re.Match[str] | None]:
    raw_href = str(row.get("href") or "").strip()
    data_href = str(row.get("dataHref") or row.get("data-href") or "").strip()
    data_url = str(row.get("dataUrl") or row.get("data-url") or "").strip()
    onclick = str(row.get("onclick") or "").strip()
    base_url = str(preset["url"])
    raw_target = raw_href or data_href or data_url
    href = urljoin(base_url, raw_target) if raw_target else ""
    # Match individual targets: joining them can append the next URL to a slug.
    match = next((found for part in (href, raw_href, data_href, data_url, onclick)
                  if part and (found := re.search(str(preset["id_pattern"]), part))), None)
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
    "Tel Aviv", "Tel-Aviv", "Tel Aviv-Yafo", "Haifa", "Herzliya", "Jerusalem", "Ramat Gan", "Petah Tikva",
    "Kiryat Gat", "Beer Sheva", "Be'er Sheva", "Yokneam", "Yoqneam", "Ra'anana",
    "Raanana", "Rehovot", "Netanya", "Caesarea", "Bnei Brak", "Rishon Lezion",
    "Kfar Saba", "Hod Hasharon", "Modiin", "Nes Ziona", "Or Yehuda", "Yehud",
    "Migdal Haemek", "Migdal Ha'Emek", "Ramat-Gan", "Tel Aviv-Yafo",
    "Kiryat Bialik", "Karmiel", "Misgav", "Holon", "Petach Tikva", "Ashdod", "Yavne",
    "Be'er Yaakov", "Beer Yaakov",
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
    "קריות": "Krayot, Israel", "קריית ביאליק": "Kiryat Bialik, Israel",
    "קרית ביאליק": "Kiryat Bialik, Israel", "כרמיאל": "Karmiel, Israel",
    "גוש שגב": "Misgav, Israel", "משגב": "Misgav, Israel",
    "באר יעקב": "Be'er Yaakov, Israel", "אשדוד": "Ashdod, Israel", "יבנה": "Yavne, Israel",
    'נתב"ג': "Ben Gurion Airport, Israel", "נתב״ג": "Ben Gurion Airport, Israel",
}


def _elbit_hashtag_location(text: str) -> str:
    """Recognize location tags, without interpreting arbitrary hashtags as cities."""
    def key(value: str) -> str:
        return re.sub(r"[\s_'’\-]+", "", value).casefold()

    names = dict(_HEBREW_ISRAEL_LOCATIONS)
    names.update({city: _extract_israel_location(city) for city in _ISRAEL_CITY_NAMES})
    names.update({value.removesuffix(", Israel"): value for value in _HEBREW_ISRAEL_LOCATIONS.values()})
    known = {key(name): location for name, location in names.items()}
    locations = []
    for tag in re.findall(r"(?<!\w)#([^#\n\r]+)", text):
        location = known.get(key(tag.strip(" .,:;")))
        if location and location not in locations:
            locations.append(location)
    return "; ".join(locations)


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
            canonical = city.replace("Tel-Aviv", "Tel Aviv").replace("Beer Sheva", "Be'er Sheva").replace("Raanana", "Ra'anana").replace("Yoqneam", "Yokneam").replace("Petach Tikva", "Petah Tikva")
            return f"{canonical}, Israel"
    # Several Israeli startup boards use ISO country codes instead of spelling out
    # the country (for example ``location_on IL`` or ``Tel Aviv · IL``). Require a
    # standalone token so words such as "skills" cannot create a false match.
    if re.search(r"(?<![A-Za-z])IL(?![A-Za-z])", compact):
        return "Israel"
    if re.search(r"(?<![A-Za-z])Israel(?![A-Za-z])", compact, re.IGNORECASE) or "ישראל" in compact:
        return "Israel"
    return ""


def _normalized_workplace(value: object) -> str:
    normalized = " ".join(str(value or "").split()).casefold()
    if "hybrid" in normalized or "היבריד" in normalized:
        return "hybrid"
    if "remote" in normalized or "מרחוק" in normalized:
        return "remote"
    if any(term in normalized for term in ("onsite", "on-site", "on site", "office", "משרד")):
        return "onsite"
    return ""
