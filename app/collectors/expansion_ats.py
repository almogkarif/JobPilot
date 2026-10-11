"""Bounded public ATS routes verified during the disabled-source audit.

Official source identities are retained: enabling a formerly pending adapter does
not create a second source or strand its historical jobs. Public Comeet embed
credentials below are published by the employers, not application credentials.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from . import audit_diagnostics as diagnostics
from ..services.job_text import clean_job_text, job_text_quality
from ..services.source_quality import is_navigation_title
from ..utils import html_to_text

MAX_RESPONSE_BYTES = 4_000_000
MAX_FEED_ROWS = 200
MAX_DESCRIPTION_CHARS = 24_000

# identifier: (Comeet slug, company UID, public embed token). Without a token,
# use the board's embedded JSON; no browser, JavaScript execution or detail crawl.
# V3 board identities were found on the public ATS. These routes remain
# partial and do not enable pending sources; live payload verification is separate.
AUDIT_V3_COMEET_IDENTIFIERS = frozenset({"fiverr", "starkware"})
COMEET_ROUTES = {
    "astrix-security": ("astrix_security", "09.009", ""),
    "chain-reaction": ("chainreaction", "A6.00D", "6AD280ED5AD5A6AD6AD6AD0D5A1AB4"),
    "kpmg-israel": ("somekhchaikin", "F3.007", "3F713D3FDCFDC17CA3F713D3BE57EEBE5"),
    # Public board identity observed in a native Retym vacancy URL. This is used
    # only as a bounded fallback for IDs still linked by Retym's own listing.
    "retym": ("retym", "C6.003", ""),
    "fiverr": ("fiverr", "60.002", ""),
    "starkware": ("starkware", "C6.00E", ""),
    # Same board and vacancy IDs as the previous HTML adapter. Read its
    # embedded payload, not Angular placeholders from individual job pages.
    "sunflower": ("sunflower", "AA.009", ""),
    "arbe": ("arbe", "C6.001", ""),
    "nova": ("nova", "A5.007", ""),
    "wiliot": ("wiliot", "F6.003", ""),
    "rapyd": ("rapyd", "73.00E", "37E11766FC1F6E11761F6E6FC01BF06FC"),
    "guesty": ("guesty", "10.000", "1030901050040401080"),
    "pentera": ("pentera", "C5.00D", "5CD1D013435289B343501D012E682E68289B"),
    "kaltura": ("kaltura", "E2.00D", "2EDEA12ED017688C7147B1A555DA2ED"),
    "natural-intelligence": ("naturalint", "71.001", "1715C47357355C45C4A17CF9CF9735"),
    "coralogix": ("coralogix", "06.004", "604241801E141E1460430200604604"),
    "personetics": ("personetics", "83.00A", "38A11B2A9E018C60153C714A9E38A"),
    "upwind": ("upwind", "49.004", "94440DC0944094401BCC12882510"),
    "earnix": ("earnix", "93.00B", "39B1207AD1AD1736736120739B193D736"),
    "papaya-global": ("papayaglobal", "16.005", ""),
    "nayax": ("nayax", "13.009", ""),
    "solaredge": ("SolarEdge", "71.00A", ""),
    "etoro": ("etoro", "41.009", ""),
    "atera": ("atera", "63.00B", ""),
    "kornit-digital": ("kornit", "11.00F", ""),
    # New employers: official career pages confirm these public board identities.
    "cognyte": ("cognyte", "F2.009", "2F9EDD2F92F911D61AC12F914CF11D62F9"),
    "cellebrite": ("Cellebrite", "C3.00F", ""),
    "scylladb": ("scylladb", "E4.006", "4E6187E1D64224A0013984E60187E"),
    "classiq": ("classiq", "F7.008", "7F82FD01FE03FC037C87F87F82FD017E847B8"),
    "oligo-security": ("oligosecurity", "5A.00B", "A5B487D296C487D01F1152D852D852D8487D"),
    "quantum-machines": ("quantummachines", "D6.000", ""),
    # Shared source expansion, checked against native public company metadata.
    "dream": ("dreamgroup", "99.002", ""),
    "riverside": ("riverside-fm", "66.009", ""),
    "8fig": ("8fig", "08.004", ""),
    "ivix": ("ivix", "09.002", ""),
    "encore": ("gainencore_ai", "0B.00C", ""),
    "sygnia": ("sygnia", "78.00A", ""),
    "zenity": ("zenity", "19.000", ""),
    "drivenets": ("drivenets", "72.006", ""),
    # Shared expansion: exact public native boards, one bounded response each.
    "buildots": ("buildots", "36.004", ""),
    "checkmarx": ("checkmarx", "C0.008", ""),
    "elementor": ("Elementor", "A3.00F", ""),
    "plainid": ("plainid", "C4.00C", ""),
    "lusha": ("lusha", "73.00B", ""),
    "cheq": ("cheq", "65.005", ""),
    "geoedge": ("geoedge.com", "82.00A", ""),
    "insightec": ("insightec", "4A.004", ""),
    "superplay": ("superplay", "28.003", ""),
    "skai": ("skai", "22.00A", ""),
    "ox-security": ("ox_security", "F8.006", ""),
    "evinced": ("evinced", "28.000", ""),
    "optibus": ("optibus", "D1.00C", ""),
    "cycode": ("cycode", "A8.00D", ""),
    "percepto": ("percepto", "44.000", ""),
    "port": ("port", "59.004", ""),
    "crossriver": ("crossriver", "C7.00F", ""),
    "comm-it": ("comm-it", "76.008", ""),
    "hypernative": ("hypernative", "8A.00E", ""),
    "codevalue": ("codevalue", "81.009", ""),
    "stampli": ("stampli", "F6.007", ""),
    "infinidat": ("infinidat", "D6.003", ""),
    "sensi-ai": ("sensi", "E7.00F", ""),
    "cardosystems": ("cardosystems", "F2.003", ""),
    "easysend": ("easysend", "D5.009", ""),
    "dualbird": ("dualbird", "2B.00C", ""),
    "inmanage": ("inmanage", "B7.006", ""),
    "final": ("final", "C0.009", ""),
    "sentra": ("sentra", "87.00B", ""),
    "zeronetworks": ("zeronetworks", "39.00F", ""),
    "mindsecurity": ("mindsecurity", "4A.00D", ""),
    "noma-security": ("noma_security", "3A.005", ""),
    "ownera": ("ownera", "59.003", ""),
    "seekingalpha": ("seekingalpha", "46.006", ""),
    "trullion": ("trullion", "07.000", ""),
    "wsc-sports": ("wsc-sports", "93.007", ""),
    "trigo": ("trigo", "A6.005", ""),
    "g2risksolutions": ("g2risksolutions", "C9.003", ""),
    "incredibuild": ("incredibuild", "66.00F", ""),
    "upstream": ("upstream", "E4.003", ""),
    "artlist": ("artlist", "85.003", ""),
    "navina": ("navina", "E6.00C", ""),
    "qodo": ("qodo", "B8.00B", ""),
    "fetcherr": ("fetcherr", "68.006", ""),
    "evoke": ("evoke", "E2.001", ""),
}
SHARED_COMEET_COMPANIES = {
    "dream": ("Dream", "www.dreamgroup.com"),
    "riverside": ("riverside.fm", "https://riverside.com"),
    "8fig": ("8fig", "https://www.8fig.co/"),
    "ivix": ("Ivix", "www.ivix.ai"),
    "encore": ("Encore AI", "https://www.gainencore.ai/"),
    "sygnia": ("Sygnia", "https://www.sygnia.co/"),
    "zenity": ("Zenity", "www.zenity.io"),
    "drivenets": ("DRIVENETS", "http://drivenets.com/"),
    "buildots": ("Buildots", 'www.buildots.com'),
    "checkmarx": ("Checkmarx", 'http://www.checkmarx.com'),
    "elementor": ("Elementor", 'https://elementor.com/'),
    "plainid": ("PlainID", 'www.plainid.com'),
    "lusha": ("Lusha", 'www.lusha.com'),
    "cheq": ("CHEQ", 'www.cheq.ai'),
    "geoedge": ("GeoEdge", 'www.geoedge.com'),
    "insightec": ("Insightec", None),
    "superplay": ("SuperPlay", 'https://www.superplay.co/'),
    "skai": ("Skai", 'www.skai.io'),
    "ox-security": ("OX Security", 'https://www.ox.security/'),
    "evinced": ("Evinced", 'www.evinced.com'),
    "optibus": ("Optibus", 'www.optibus.com'),
    "cycode": ("Cycode", 'https://cycode.com/'),
    "percepto": ("Percepto", 'https://percepto.com/'),
    "port": ("Port", 'https://www.port.io/'),
    "crossriver": ("Cross River", 'crossriver.com'),
    "comm-it": ("CommIT", 'www.comm-it.com'),
    "hypernative": ("Hypernative", 'https://www.hypernative.io/'),
    "codevalue": ("CodeValue", 'https://codevalue1.webflow.io'),
    "stampli": ("Stampli", 'https://www.stampli.com/'),
    "infinidat": ("INFINIDAT", 'https://www.infinidat.com/en/careers'),
    "sensi-ai": ("Sensi.AI", 'https://sensi.ai/'),
    "cardosystems": ("Cardo Systems", 'www.cardosystems.com'),
    "easysend": ("EasySend", 'https://www.easysend.io/'),
    "dualbird": ("Dualbird", 'www.dualbird.io'),
    "inmanage": ("inManage", 'https://www.inmanage.co.il/'),
    "final": ("Final", 'www.final.co.il'),
    "sentra": ("Sentra", 'www.sentra.io'),
    "zeronetworks": ("Zero Networks", 'https://zeronetworks.com/'),
    "mindsecurity": ("Mind Security Inc.", 'www.mind.io'),
    "noma-security": ("Noma Security", 'https://noma.security/'),
    "ownera": ("Ownera", 'https://ownera.io/'),
    "seekingalpha": ("Seeking Alpha", 'https://seekingalpha.com/'),
    "trullion": ("Trullion", 'https://trullion.com/'),
    "wsc-sports": ("WSC Sports", 'https://wsc-sports.com/'),
    "trigo": ("Trigo", 'https://www.trigoretail.com/'),
    "g2risksolutions": ("G2 Risk Solutions", 'https://g2risksolutions.com/'),
    "incredibuild": ("Incredibuild", 'www.incredibuild.com'),
    "upstream": ("Upstream Security", 'https://www.upstream.auto/'),
    "artlist": ("Artlist", 'https://artlist.io/'),
    "navina": ("Navina", 'https://www.navina.ai'),
    "qodo": ("Qodo", 'https://www.qodo.ai/'),
    "fetcherr": ("Fetcherr", 'https://www.fetcherr.io/'),
    "evoke": ("evoke", 'https://www.evokeplc.com/'),
}
GREENHOUSE_ROUTES = {"tipalti": "tipaltisolutions"}
HIBOB_ROUTES = {"hibob": "hibob-fa0ad69d0cb34a", "fundbox": "fundbox"}
LEVER_ROUTES = {"d-fend-solutions": "d-fendsolutions"}
# Retym remains a primary-HTML source; this board is fallback-only, not a
# newly verified/default-enabled source.
VERIFIED_ATS_IDENTIFIERS = (frozenset(COMEET_ROUTES) - {"retym"}) | frozenset(GREENHOUSE_ROUTES) | frozenset(HIBOB_ROUTES) | frozenset(LEVER_ROUTES) | {"lemonade"}


def endpoint_for(identifier: str) -> str:
    if identifier == "lemonade":
        return "https://makers.lemonade.com/"
    if identifier in HIBOB_ROUTES:
        return f"https://{HIBOB_ROUTES[identifier]}.careers.hibob.com/api/job-ad"
    if identifier in GREENHOUSE_ROUTES:
        return f"https://boards-api.greenhouse.io/v1/boards/{GREENHOUSE_ROUTES[identifier]}/jobs?content=true"
    if identifier in LEVER_ROUTES:
        return f"https://api.lever.co/v0/postings/{LEVER_ROUTES[identifier]}?mode=json"
    slug, uid, token = COMEET_ROUTES[identifier]
    if token:
        return f"https://www.comeet.co/careers-api/2.0/company/{uid}/positions?token={token}&details=true"
    return f"https://www.comeet.com/jobs/{slug}/{uid}"


async def bounded_public_get(url: str, *, headers: dict | None = None) -> str:
    """One response, with a decompressed-byte cap; redirects fail closed."""
    async with httpx.AsyncClient(timeout=25, follow_redirects=False, headers=headers) as client:
        async with client.stream("GET", url) as response:
            if response.is_redirect:
                raise PreserveExistingJobs("Public ATS unexpectedly redirected")
            response.raise_for_status()
            chunks = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise PreserveExistingJobs("Public ATS exceeded the 4 MB response limit")
                chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


def parse_expansion_feed(identifier: str, document: str, company: str) -> JobCollection:
    if len(document.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise PreserveExistingJobs("Public ATS exceeded the 4 MB response limit")
    greenhouse = identifier in GREENHOUSE_ROUTES
    hibob = identifier in HIBOB_ROUTES
    lemonade = identifier == "lemonade"
    lever = identifier in LEVER_ROUTES
    try:
        if lemonade:
            script = BeautifulSoup(document, "html.parser").select_one("#__NEXT_DATA__")
            payload = json.loads(script.get_text() if script else "{}")
            payload = payload.get("props", {}).get("pageProps", {}).get("allRecipes")
        elif not greenhouse and not hibob and not lever and not COMEET_ROUTES[identifier][2]:
            if identifier == "astrix-security" or identifier in SHARED_COMEET_COMPANIES:
                company_marker = re.search(r"\bCOMPANY_DATA\s*=\s*", document)
                if not company_marker:
                    raise ValueError("Missing company identity")
                company_data, _ = json.JSONDecoder().raw_decode(document[company_marker.end():])
                name, website = SHARED_COMEET_COMPANIES.get(identifier, ("Astrix Security", "https://astrix.security/"))
                if (not isinstance(company_data, dict) or company_data.get("name") != name
                        or company_data.get("website") != website
                        or company_data.get("url_comeet_hosted_page") != endpoint_for(identifier)):
                    raise ValueError("Unexpected company identity")
            marker = re.search(r"\bCOMPANY_POSITIONS_DATA\s*=\s*", document)
            if not marker:
                raise ValueError("Missing embedded jobs")
            payload, _ = json.JSONDecoder().raw_decode(document[marker.end():])
        else:
            payload = json.loads(document)
        rows = (payload.get("jobAdDetails" if hibob else "jobs")
                if (greenhouse or hibob) and isinstance(payload, dict) else payload)
    except (ValueError, TypeError) as exc:
        diagnostics.record("ats_payload_rejected", identifier=identifier, reason="unrecognized_schema",
                           error_type=type(exc).__name__)
        raise PreserveExistingJobs("Public ATS returned an unrecognized payload") from exc
    diagnostics.record("ats_payload", identifier=identifier, shape=type(rows).__name__,
                       row_count=len(rows) if isinstance(rows, list) else None,
                       row_limit=MAX_FEED_ROWS)
    if not isinstance(rows, list):
        raise PreserveExistingJobs("Public ATS feed has an invalid row container (expected a list)")
    if not rows:
        # This company UID/slug and currently empty list were independently
        # verified against the employer's published embed and company metadata.
        # Partial means the empty response still cannot retire existing jobs.
        if identifier in {"chain-reaction", "astrix-security"}:
            return JobCollection([], complete=False)
        raise PreserveExistingJobs("Public ATS feed returned an empty list; employer-wide absence is unverified")
    if len(rows) > MAX_FEED_ROWS:
        raise PreserveExistingJobs(f"Public ATS feed exceeded the {MAX_FEED_ROWS}-row limit ({len(rows)} rows)")
    jobs = {}
    rejections = {"non_object": 0, "location_shape": 0, "details_missing": 0,
                  "identity": 0, "url": 0, "title": 0, "description": 0}
    for row in rows:
        if not isinstance(row, dict):
            rejections["non_object"] += 1
            continue
        title = clean_job_text(row.get("text") if lever else row.get("title") if greenhouse or hibob or lemonade else row.get("name"))[:500]
        external_id = str(row.get("postingId") if lemonade else row.get("id") if greenhouse or hibob or lever else row.get("uid") or "")
        categories = row.get("categories") if lever else None
        if lever and not isinstance(categories, dict):
            rejections["location_shape"] += 1
            continue
        location_data = ({"name": ", ".join(str(row[key]) for key in ("site", "country") if row.get(key))}
                         if hibob else {"name": categories.get("location"), "country": row.get("country")}
                         if lever else {"name": row.get("location")} if lemonade else row.get("location") or {})
        if not isinstance(location_data, dict):
            rejections["location_shape"] += 1
            continue
        location = str(location_data.get("name") or "")[:500]
        if str(location_data.get("country") or "").upper() == "IL" and "israel" not in location.casefold():
            location = f"{location}, Israel".strip(", ")
        if identifier == "retym" and location.strip().casefold() in {
            "ramat-gan (tel-aviv area)", "ramat gan (tel aviv area)"
        }:
            # This is the exact office field, not a company address in the body.
            location = "Ramat Gan, Israel"
        if lever:
            valid_id = re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", external_id)
            url = str(row.get("hostedUrl") or "")
            parsed = urlparse(url)
            valid_url = (parsed.scheme == "https" and parsed.hostname == "jobs.lever.co"
                         and parsed.path == f"/{LEVER_ROUTES[identifier]}/{external_id}")
            sections = row.get("lists") or []
            if not isinstance(sections, list) or len(sections) > 30 or any(not isinstance(part, dict) for part in sections):
                rejections["details_missing"] += 1
                continue
            description = clean_job_text("\n".join(
                [html_to_text(row.get("description"))]
                + [f"{clean_job_text(part.get('text'))}\n{html_to_text(part.get('content'))}" for part in sections]
                + [html_to_text(row.get("additional"))]
            ))
        elif lemonade:
            valid_id = re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", external_id)
            url = str(row.get("link") or "")
            parsed = urlparse(url)
            valid_url = (parsed.scheme == "https" and parsed.hostname == "makers.lemonade.com"
                         and parsed.path.startswith("/role/") and parsed.path.endswith(str(row.get("slug") or "")))
            description = html_to_text(row.get("content"))
        elif hibob:
            valid_id = re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", external_id)
            url = f"https://{HIBOB_ROUTES[identifier]}.careers.hibob.com/jobs/{external_id}"
            valid_url = bool(valid_id)
            description = clean_job_text("\n".join(
                str(row.get(key) or "") for key in ("description", "requirements", "responsibilities", "benefits")
            ))
        elif greenhouse:
            url = str(row.get("absolute_url") or "")
            valid_id = re.fullmatch(r"\d+", external_id)
            parsed = urlparse(url)
            valid_url = parsed.scheme == "https" and parsed.hostname in {"tipalti.com", "www.tipalti.com"}
            description = html_to_text(row.get("content"))
        else:
            slug, uid, _ = COMEET_ROUTES[identifier]
            url = str(row.get("url_comeet_hosted_page") or "")
            parsed = urlparse(url)
            valid_id = re.fullmatch(r"[A-Za-z0-9]{2}\.[A-Za-z0-9]{3}(?:-[A-Za-z0-9]{2}\.[A-Za-z0-9]{3})?", external_id)
            valid_url = (parsed.scheme == "https" and parsed.hostname == "www.comeet.com"
                         and parsed.path.startswith(f"/jobs/{slug}/{uid}/")
                         and parsed.path.rstrip("/").split("/")[-1] == external_id)
            if identifier in SHARED_COMEET_COMPANIES:
                valid_url = (valid_url and not parsed.username and not parsed.password
                             and not parsed.query and not parsed.fragment and parsed.netloc == "www.comeet.com")
            custom_fields = row.get("custom_fields")
            details = row.get("details") or (custom_fields.get("details") if isinstance(custom_fields, dict) else None)
            if not isinstance(details, list) or len(details) > 30:
                rejections["details_missing"] += 1
                continue
            description = clean_job_text("\n".join(
                f"{part.get('name', '')}\n{clean_job_text(part.get('value'))}"
                for part in details if isinstance(part, dict) and part.get("value")
            ))
        reason = ("identity" if not valid_id else "url" if not valid_url else
                  "title" if not title or is_navigation_title(title) else
                  "description" if len(description) > MAX_DESCRIPTION_CHARS or job_text_quality(description) != "complete" else None)
        if reason:
            rejections[reason] += 1
            continue
        if external_id in jobs:
            raise PreserveExistingJobs("Public ATS returned duplicate vacancy identities")
        jobs[external_id] = NormalizedJob(
            external_id=external_id, title=title, company=company, location=location,
            workplace=(str(row.get("workplaceType")).lower()
                       if lever and str(row.get("workplaceType")).lower() in {"remote", "hybrid", "onsite"}
                       else "unknown"),
            description=description, apply_url=url, source_url=url,
        )
    diagnostics.record("ats_result", identifier=identifier, accepted=len(jobs), rejected=rejections)
    if not jobs:
        raise PreserveExistingJobs("Public ATS exposed no complete verified vacancies")
    # Preserve legacy snapshots; partial/malformed rows never imply job closure.
    return JobCollection(jobs.values(), complete=False)


async def collect_expansion_feed(identifier: str, company: str) -> JobCollection:
    headers = {"companyIdentifier": HIBOB_ROUTES[identifier]} if identifier in HIBOB_ROUTES else None
    document = (await bounded_public_get(endpoint_for(identifier), headers=headers)
                if headers else await bounded_public_get(endpoint_for(identifier)))
    if not headers and not COMEET_ROUTES.get(identifier, ("", "", ""))[2]:
        diagnostics.document(endpoint_for(identifier), document)
    return parse_expansion_feed(identifier, document, company)
