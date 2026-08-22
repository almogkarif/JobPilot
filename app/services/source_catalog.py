from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, Source
from .career_tracks import COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, ELECTRICAL_ENGINEERING, DEFAULT_TRACK, normalize_track
from ..utils import dumps, loads

# Public ATS boards that regularly publish relevant roles in Israel.
# Source rows are track-scoped: the same company may exist in both tracks with
# independent enable/error state, while only the active track is ever scanned.
CS_RECOMMENDED_SOURCES: tuple[dict[str, str], ...] = (
    {"name": "Google Careers Israel", "kind": "google_careers", "identifier": "israel", "company_name": "Google"},
    {"name": "Apple Careers Israel", "kind": "official_careers", "identifier": "apple", "company_name": "Apple"},
    {"name": "Amazon Jobs Israel", "kind": "official_careers", "identifier": "amazon", "company_name": "Amazon"},
    {"name": "NVIDIA Careers Israel", "kind": "workday", "identifier": "nvidia", "company_name": "NVIDIA"},
    {"name": "Intel Careers Israel", "kind": "workday", "identifier": "intel", "company_name": "Intel"},
    {"name": "Microsoft Careers Israel", "kind": "official_careers", "identifier": "microsoft", "company_name": "Microsoft"},
    {"name": "Mobileye Careers Israel", "kind": "lever", "identifier": "eu:mobileye", "company_name": "Mobileye"},
    {"name": "Check Point Careers Israel", "kind": "official_careers", "identifier": "checkpoint", "company_name": "Check Point"},
    {"name": "Palo Alto Networks Israel", "kind": "official_careers", "identifier": "paloalto", "company_name": "Palo Alto Networks"},
    {"name": "Wix Careers Israel", "kind": "official_careers", "identifier": "wix", "company_name": "Wix"},
    {"name": "monday.com Careers Israel", "kind": "official_careers", "identifier": "monday", "company_name": "monday.com"},
    {"name": "Cisco Careers Israel", "kind": "official_careers", "identifier": "cisco", "company_name": "Cisco"},
    {"name": "IBM Careers Israel", "kind": "official_careers", "identifier": "ibm", "company_name": "IBM"},
    {"name": "Salesforce Careers Israel", "kind": "official_careers", "identifier": "salesforce", "company_name": "Salesforce"},
    {"name": "Meta Careers Israel", "kind": "official_careers", "identifier": "meta", "company_name": "Meta"},
    {"name": "Qualcomm Careers Israel", "kind": "official_careers", "identifier": "qualcomm", "company_name": "Qualcomm"},
    {"name": "Samsung Research Israel", "kind": "official_careers", "identifier": "samsung", "company_name": "Samsung Research Israel"},
    {"name": "Applied Materials Israel", "kind": "workday", "identifier": "applied-materials", "company_name": "Applied Materials"},
    {"name": "Philips Careers Israel", "kind": "official_careers", "identifier": "philips", "company_name": "Philips"},
    {"name": "Elbit Systems Careers", "kind": "official_careers", "identifier": "elbit", "company_name": "Elbit Systems"},
    {"name": "Rafael Careers", "kind": "official_careers", "identifier": "rafael", "company_name": "Rafael"},
    {"name": "IAI Careers", "kind": "official_careers", "identifier": "iai", "company_name": "Israel Aerospace Industries"},
    {"name": "Taboola Careers Israel", "kind": "greenhouse", "identifier": "taboola", "company_name": "Taboola"},
    {"name": "AppsFlyer Careers Israel", "kind": "official_careers", "identifier": "appsflyer", "company_name": "AppsFlyer"},
    {"name": "Similarweb Careers Israel", "kind": "greenhouse", "identifier": "similarweb", "company_name": "Similarweb"},
    {"name": "Outbrain Careers Israel", "kind": "greenhouse", "identifier": "outbraininc", "company_name": "Outbrain"},
    {"name": "CyberArk Careers Israel", "kind": "smartrecruiters", "identifier": "Cyberark1", "company_name": "CyberArk"},
    {"name": "Cato Networks Careers", "kind": "official_careers", "identifier": "cato", "company_name": "Cato Networks"},
    {"name": "Wiz Careers Israel", "kind": "official_careers", "identifier": "wiz", "company_name": "Wiz"},
    {"name": "Orca Security Careers", "kind": "greenhouse", "identifier": "orcasecurity", "company_name": "Orca Security"},
    {"name": "SentinelOne Careers Israel", "kind": "official_careers", "identifier": "sentinelone", "company_name": "SentinelOne"},
    {"name": "Aqua Security Careers", "kind": "official_careers", "identifier": "aqua", "company_name": "Aqua Security"},
    {"name": "Figma Careers", "kind": "greenhouse", "identifier": "figma", "company_name": "Figma"},
    {"name": "Speechify Careers", "kind": "greenhouse", "identifier": "speechify", "company_name": "Speechify"},
    {"name": "Pagaya Israel Careers", "kind": "greenhouse", "identifier": "pagayais", "company_name": "Pagaya"},
    {"name": "Tenable Careers", "kind": "greenhouse", "identifier": "tenableinc", "company_name": "Tenable"},
    {"name": "Redis Careers", "kind": "ashby", "identifier": "redis", "company_name": "Redis"},
    {"name": "Tavily Careers", "kind": "ashby", "identifier": "tavily", "company_name": "Tavily"},
    {"name": "Nexxen Careers", "kind": "ashby", "identifier": "nexxen", "company_name": "Nexxen"},
    {"name": "Chainalysis Careers", "kind": "ashby", "identifier": "chainalysis-careers", "company_name": "Chainalysis"},
    {"name": "Reindeer AI Careers", "kind": "ashby", "identifier": "reindeer-ai", "company_name": "Reindeer AI"},
    {"name": "TRAILD Careers", "kind": "lever", "identifier": "traildsoftware", "company_name": "TRAILD"},
    {"name": "NICE Careers Israel", "kind": "greenhouse", "identifier": "nice", "company_name": "NICE"},
    {"name": "Riskified Careers Israel", "kind": "greenhouse", "identifier": "riskified", "company_name": "Riskified"},
    {"name": "Sunflower Careers Israel", "kind": "official_careers", "identifier": "sunflower", "company_name": "Sunflower"},
    {"name": "Moon Active Careers Israel", "kind": "official_careers", "identifier": "moonactive", "company_name": "Moon Active"},
    {"name": "Connecteam Careers Israel", "kind": "official_careers", "identifier": "connecteam", "company_name": "Connecteam"},
    {"name": "Via Careers Israel", "kind": "greenhouse", "identifier": "via", "company_name": "Via"},
    {"name": "Apiiro Careers Israel", "kind": "greenhouse", "identifier": "apiiro", "company_name": "Apiiro"},
    {"name": "SafeBreach Careers Israel", "kind": "greenhouse", "identifier": "safebreach", "company_name": "SafeBreach"},
    {"name": "Guidde Careers Israel", "kind": "greenhouse", "identifier": "guidde", "company_name": "Guidde"},
    {"name": "ScaleOps Careers Israel", "kind": "greenhouse", "identifier": "scaleops", "company_name": "ScaleOps"},
    {"name": "Sweet Security Careers Israel", "kind": "greenhouse", "identifier": "sweetsecurity", "company_name": "Sweet Security"},
    {"name": "accessiBe Careers Israel", "kind": "greenhouse", "identifier": "accessibe", "company_name": "accessiBe"},
    {"name": "Unframe Careers Israel", "kind": "greenhouse", "identifier": "unframe", "company_name": "Unframe"},
    {"name": "Descope Careers Israel", "kind": "greenhouse", "identifier": "descope", "company_name": "Descope"},
    {"name": "Guardz Careers Israel", "kind": "greenhouse", "identifier": "guardz", "company_name": "Guardz"},
    {"name": "Bluevine Israel Careers", "kind": "greenhouse", "identifier": "bluevineisrael", "company_name": "Bluevine"},
    {"name": "Pendo Careers Israel", "kind": "greenhouse", "identifier": "pendo", "company_name": "Pendo"},
    {"name": "BeamUP Careers Israel", "kind": "greenhouse", "identifier": "beamup", "company_name": "BeamUP"},
    {"name": "Daylight Security Careers Israel", "kind": "greenhouse", "identifier": "daylightsecurity", "company_name": "Daylight Security"},
    {"name": "Aidoc Engineering Israel", "kind": "greenhouse", "identifier": "aidocmedical", "company_name": "Aidoc"},
    {"name": "Armis Engineering Israel", "kind": "greenhouse", "identifier": "armissecurity", "company_name": "Armis"},
    {"name": "Forter Engineering Israel", "kind": "greenhouse", "identifier": "forter", "company_name": "Forter"},
    {"name": "Gong Engineering Israel", "kind": "greenhouse", "identifier": "gongio", "company_name": "Gong"},
    {"name": "Torq Engineering Israel", "kind": "greenhouse", "identifier": "torq", "company_name": "Torq"},
    {"name": "Datarails Careers Israel", "kind": "greenhouse", "identifier": "datarails", "company_name": "Datarails"},
    {"name": "Cymulate Careers Israel", "kind": "greenhouse", "identifier": "cymulate", "company_name": "Cymulate"},
    {"name": "QuantHealth Engineering Israel", "kind": "greenhouse", "identifier": "quanthealth", "company_name": "QuantHealth"},
    {"name": "Eleos Health Engineering Israel", "kind": "greenhouse", "identifier": "eleoshealth", "company_name": "Eleos Health"},
    {"name": "Melio Engineering Israel", "kind": "greenhouse", "identifier": "melio", "company_name": "Melio"},
    {"name": "Neo Security Engineering Israel", "kind": "greenhouse", "identifier": "neosecurityinc", "company_name": "Neo Security"},
)

# Industrial Engineering & Management focuses on employers with manufacturing,
# operations, planning, supply-chain, analytics, PMO and business-operations roles.
# Several are shared companies, but they are independent Source rows in this track.
IEM_RECOMMENDED_SOURCES: tuple[dict[str, str], ...] = (
    {"name": "Applied Materials — Operations Israel", "kind": "workday", "identifier": "applied-materials", "company_name": "Applied Materials"},
    {"name": "Intel — Manufacturing & Supply Chain Israel", "kind": "workday", "identifier": "intel", "company_name": "Intel"},
    {"name": "KLA Israel — Operations", "kind": "workday", "identifier": "kla-israel", "company_name": "KLA"},
    {"name": "Medtronic Israel — Operations", "kind": "workday", "identifier": "medtronic", "company_name": "Medtronic"},
    {"name": "Mobileye — Project & Operations", "kind": "lever", "identifier": "eu:mobileye", "company_name": "Mobileye"},
    {"name": "Elbit Systems — תעשייה וניהול", "kind": "official_careers", "identifier": "elbit", "company_name": "Elbit Systems"},
    {"name": "Rafael — תעשייה וניהול", "kind": "official_careers", "identifier": "rafael", "company_name": "Rafael"},
    {"name": "IAI — תעשייה וניהול", "kind": "official_careers", "identifier": "iai", "company_name": "Israel Aerospace Industries"},
    {"name": "Philips Israel — Operations", "kind": "official_careers", "identifier": "philips", "company_name": "Philips"},
    {"name": "Amazon Israel — Operations", "kind": "official_careers", "identifier": "amazon", "company_name": "Amazon"},
    {"name": "NVIDIA Israel — Operations & Planning", "kind": "workday", "identifier": "nvidia", "company_name": "NVIDIA"},
    {"name": "Google Israel — Business & Operations", "kind": "google_careers", "identifier": "israel", "company_name": "Google"},
    {"name": "Microsoft Israel — Business Operations", "kind": "official_careers", "identifier": "microsoft", "company_name": "Microsoft"},
    {"name": "Salesforce Israel — Business Operations", "kind": "official_careers", "identifier": "salesforce", "company_name": "Salesforce"},
    {"name": "monday.com — Operations & Analytics", "kind": "official_careers", "identifier": "monday", "company_name": "monday.com"},
    {"name": "Wix — Operations & Analytics", "kind": "official_careers", "identifier": "wix", "company_name": "Wix"},
    {"name": "Taboola — Business Operations", "kind": "greenhouse", "identifier": "taboola", "company_name": "Taboola"},
    {"name": "Similarweb — Business & Data", "kind": "greenhouse", "identifier": "similarweb", "company_name": "Similarweb"},
    {"name": "AppsFlyer — Operations & Analytics", "kind": "official_careers", "identifier": "appsflyer", "company_name": "AppsFlyer"},
    {"name": "Pagaya — Operations & Analytics", "kind": "greenhouse", "identifier": "pagayais", "company_name": "Pagaya"},
    {"name": "Check Point — Operations", "kind": "official_careers", "identifier": "checkpoint", "company_name": "Check Point"},
    {"name": "CyberArk — Business Operations", "kind": "smartrecruiters", "identifier": "Cyberark1", "company_name": "CyberArk"},
    {"name": "Aidoc — Operations & Product Analytics", "kind": "greenhouse", "identifier": "aidocmedical", "company_name": "Aidoc"},
    {"name": "Axon — Program & R&D Operations Israel", "kind": "greenhouse", "identifier": "axon", "company_name": "Axon"},
    {"name": "Gong — Operational Excellence & Analytics", "kind": "greenhouse", "identifier": "gongio", "company_name": "Gong"},
    {"name": "Armis — Data & Program Operations", "kind": "greenhouse", "identifier": "armissecurity", "company_name": "Armis"},
    {"name": "Forter — Business & Finance Operations", "kind": "greenhouse", "identifier": "forter", "company_name": "Forter"},
    {"name": "Torq — Business Analysis & Operations", "kind": "greenhouse", "identifier": "torq", "company_name": "Torq"},
    {"name": "QuantHealth — Operations Israel", "kind": "greenhouse", "identifier": "quanthealth", "company_name": "QuantHealth"},
    {"name": "Wolt — Supply Chain & Operations Israel", "kind": "greenhouse", "identifier": "wolt", "company_name": "Wolt"},
    {"name": "Eleos Health — Operations & Process Improvement", "kind": "greenhouse", "identifier": "eleoshealth", "company_name": "Eleos Health"},
    {"name": "Ashley Digital — BI & Data Solutions Israel", "kind": "greenhouse", "identifier": "residenthome", "company_name": "Ashley Digital"},
    {"name": "NICE — Analytics & Operations Israel", "kind": "greenhouse", "identifier": "nice", "company_name": "NICE"},
    {"name": "Riskified — Data & Operations Israel", "kind": "greenhouse", "identifier": "riskified", "company_name": "Riskified"},
    {"name": "Sunflower — Business & Operations Israel", "kind": "official_careers", "identifier": "sunflower", "company_name": "Sunflower"},
    {"name": "Moon Active — Product & Operations Israel", "kind": "official_careers", "identifier": "moonactive", "company_name": "Moon Active"},
    {"name": "Connecteam — Product & Operations Israel", "kind": "official_careers", "identifier": "connecteam", "company_name": "Connecteam"},
    {"name": "Datarails — Finance & Operations Israel", "kind": "greenhouse", "identifier": "datarails", "company_name": "Datarails"},
    {"name": "Cymulate — Operations Israel", "kind": "greenhouse", "identifier": "cymulate", "company_name": "Cymulate"},
)


EE_RECOMMENDED_SOURCES: tuple[dict[str, str], ...] = (
    {"name":"NVIDIA — Hardware Israel","kind":"workday","identifier":"nvidia","company_name":"NVIDIA"},
    {"name":"Intel — Hardware & Silicon Israel","kind":"workday","identifier":"intel","company_name":"Intel"},
    {"name":"Apple — Hardware Israel","kind":"official_careers","identifier":"apple","company_name":"Apple"},
    {"name":"Qualcomm — Hardware Israel","kind":"official_careers","identifier":"qualcomm","company_name":"Qualcomm"},
    {"name":"Mobileye — Hardware & Embedded","kind":"lever","identifier":"eu:mobileye","company_name":"Mobileye"},
    {"name":"Amazon — Annapurna Labs Israel","kind":"official_careers","identifier":"amazon","company_name":"Amazon"},
    {"name":"Applied Materials — Electrical & Hardware","kind":"workday","identifier":"applied-materials","company_name":"Applied Materials"},
    {"name":"KLA Israel — Electrical & Systems","kind":"workday","identifier":"kla-israel","company_name":"KLA"},
    {"name":"Rafael — Electrical Engineering","kind":"official_careers","identifier":"rafael","company_name":"Rafael"},
    {"name":"Elbit Systems — Electrical Engineering","kind":"official_careers","identifier":"elbit","company_name":"Elbit Systems"},
    {"name":"IAI — Electrical Engineering","kind":"official_careers","identifier":"iai","company_name":"Israel Aerospace Industries"},
    {"name":"Cisco — Silicon & Hardware Israel","kind":"official_careers","identifier":"cisco","company_name":"Cisco"},
    {"name":"Microsoft — Silicon Israel","kind":"official_careers","identifier":"microsoft","company_name":"Microsoft"},
    {"name":"Samsung Research Israel — Hardware","kind":"official_careers","identifier":"samsung","company_name":"Samsung Research Israel"},
    {"name":"Valens Semiconductor — Hardware Israel","kind":"official_careers","identifier":"valens","company_name":"Valens Semiconductor"},
    {"name":"NextSilicon — Hardware Israel","kind":"official_careers","identifier":"nextsilicon","company_name":"NextSilicon"},
    {"name":"Retym — Semiconductor Israel","kind":"official_careers","identifier":"retym","company_name":"Retym"},
    {"name":"Hailo — AI Silicon Israel","kind":"official_careers","identifier":"hailo","company_name":"Hailo"},
    {"name":"Pliops — Storage Silicon Israel","kind":"official_careers","identifier":"pliops","company_name":"Pliops"},
    {"name":"Chain Reaction — Hardware Israel","kind":"official_careers","identifier":"chain-reaction","company_name":"Chain Reaction"},
    {"name":"SCD — SemiConductor Devices","kind":"official_careers","identifier":"scd","company_name":"SCD - SemiConductor Devices"},
    {"name":"Cadence Design Systems — Israel","kind":"official_careers","identifier":"cadence","company_name":"Cadence Design Systems"},
    {"name":"Texas Instruments — Israel","kind":"official_careers","identifier":"texas-instruments","company_name":"Texas Instruments"},
    {"name":"Flex — Hardware Israel","kind":"official_careers","identifier":"flex-israel","company_name":"Flex"},
    {"name":"Siemens EDA — Israel","kind":"official_careers","identifier":"siemens-eda","company_name":"Siemens EDA"},
    {"name":"Google — Hardware Israel","kind":"google_careers","identifier":"israel","company_name":"Google"},
    {"name":"Marvell — Israel","kind":"official_careers","identifier":"marvell","company_name":"Marvell"},
    {"name":"Broadcom — Israel","kind":"official_careers","identifier":"broadcom-israel","company_name":"Broadcom"},
    {"name":"Synopsys — Israel","kind":"official_careers","identifier":"synopsys-israel","company_name":"Synopsys"},
    {"name":"Arm — Israel","kind":"official_careers","identifier":"arm-israel","company_name":"Arm"},
    {"name":"DustPhotonics — Israel","kind":"official_careers","identifier":"dustphotonics","company_name":"DustPhotonics"},
    {"name":"Wiliot — Hardware Israel","kind":"official_careers","identifier":"wiliot","company_name":"Wiliot"},
    {"name":"Vayyar Imaging — Israel","kind":"official_careers","identifier":"vayyar","company_name":"Vayyar Imaging"},
    {"name":"Arbe Robotics — Israel","kind":"official_careers","identifier":"arbe","company_name":"Arbe Robotics"},
    {"name":"TriEye — Israel","kind":"official_careers","identifier":"trieye","company_name":"TriEye"},
    {"name":"Speedata — Israel","kind":"official_careers","identifier":"speedata","company_name":"Speedata"},
    {"name":"proteanTecs — Israel","kind":"official_careers","identifier":"proteantecs","company_name":"proteanTecs"},
    {"name":"Innoviz — Israel","kind":"official_careers","identifier":"innoviz","company_name":"Innoviz"},
    {"name":"Camtek — Israel","kind":"official_careers","identifier":"camtek","company_name":"Camtek"},
    {"name":"Nova — Israel","kind":"official_careers","identifier":"nova","company_name":"Nova Measuring Instruments"},
    {"name":"NeuroBlade — Israel","kind":"official_careers","identifier":"neuroblade","company_name":"NeuroBlade"},
)

RECOMMENDED_SOURCES_BY_TRACK = {
    COMPUTER_SCIENCE: CS_RECOMMENDED_SOURCES,
    INDUSTRIAL_ENGINEERING: IEM_RECOMMENDED_SOURCES,
    ELECTRICAL_ENGINEERING: EE_RECOMMENDED_SOURCES,
}
# Backward-compatible symbol used by older tests/imports.
RECOMMENDED_SOURCES = CS_RECOMMENDED_SOURCES


def _source_key(source: Source | dict[str, str]) -> tuple[str, str]:
    kind = str(source.kind if isinstance(source, Source) else source.get("kind", "")).strip().casefold()
    identifier = str(source.identifier if isinstance(source, Source) else source.get("identifier", "")).strip().casefold()
    return kind, identifier


def _company_key(source: Source | dict[str, str]) -> str:
    value = source.company_name if isinstance(source, Source) else source.get("company_name", "")
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _is_catalog_managed(source: Source) -> bool:
    metadata = loads(source.metadata_json, {})
    return isinstance(metadata, dict) and (metadata.get("preset") == "recommended" or metadata.get("duplicate_of"))


def suppress_duplicate_sources(db: Session, career_track: str = DEFAULT_TRACK) -> int:
    """Hide/disable duplicate source rows without deleting historical jobs.

    Legacy installs can contain the same ATS board more than once after collector
    migrations or repeated seed runs. Deleting those rows would risk historical job
    relationships, so duplicates are marked and disabled while one canonical row is
    kept visible and scan-enabled.
    """
    career_track = normalize_track(career_track)
    catalog = recommended_sources_for_track(career_track)
    catalog_by_key = {_source_key(item): item for item in catalog}
    catalog_by_company = {_company_key(item): item for item in catalog if _company_key(item)}
    rows = db.scalars(select(Source).where(Source.career_track == career_track).order_by(Source.id)).all()

    # First collapse literal duplicates (same collector + identifier). Then collapse
    # legacy recommended rows whose collector type changed over time, e.g. an old
    # ``official_careers/taboola`` row next to today's ``greenhouse/taboola`` row.
    # User-created custom sources are never hidden merely because the company name
    # matches a preset; cross-kind reconciliation is restricted to catalog-managed
    # rows so we do not erase an intentionally-added second board.
    groups: list[tuple[dict[str, str] | None, list[Source]]] = []
    exact_groups: dict[tuple[str, str], list[Source]] = {}
    for source in rows:
        exact_groups.setdefault(_source_key(source), []).append(source)
    groups.extend((catalog_by_key.get(key), duplicates) for key, duplicates in exact_groups.items() if len(duplicates) > 1)

    company_groups: dict[str, list[Source]] = {}
    for source in rows:
        key = _company_key(source)
        if key in catalog_by_company and _is_catalog_managed(source):
            company_groups.setdefault(key, []).append(source)
    for key, duplicates in company_groups.items():
        if len(duplicates) > 1:
            groups.append((catalog_by_company[key], duplicates))

    changed = 0
    processed: set[tuple[int, ...]] = set()
    for preferred, duplicates in groups:
        signature = tuple(sorted(row.id for row in duplicates))
        if signature in processed:
            continue
        processed.add(signature)
        preferred_key = _source_key(preferred) if preferred else None
        canonical = next((row for row in duplicates if preferred_key and _source_key(row) == preferred_key), None)
        canonical = canonical or next((row for row in duplicates if preferred and row.name == preferred["name"]), duplicates[0])
        if preferred:
            if canonical.name != preferred["name"]:
                canonical.name = preferred["name"]; changed += 1
            if canonical.company_name != preferred["company_name"]:
                canonical.company_name = preferred["company_name"]; changed += 1
        canonical_meta = loads(canonical.metadata_json, {})
        if not isinstance(canonical_meta, dict):
            canonical_meta = {}
        if canonical_meta.pop("duplicate_of", None) is not None:
            canonical.metadata_json = dumps(canonical_meta)
            changed += 1
        for duplicate in duplicates:
            if duplicate.id == canonical.id:
                continue
            meta = loads(duplicate.metadata_json, {})
            if not isinstance(meta, dict):
                meta = {}
            if duplicate.enabled or meta.get("duplicate_of") != canonical.id:
                duplicate.enabled = False
                meta["duplicate_of"] = canonical.id
                duplicate.metadata_json = dumps(meta)
                changed += 1
    return changed


def recommended_sources_for_track(career_track: str = DEFAULT_TRACK) -> tuple[dict[str, str], ...]:
    return RECOMMENDED_SOURCES_BY_TRACK[normalize_track(career_track)]


def install_recommended_sources(db: Session, career_track: str = DEFAULT_TRACK) -> int:
    """Install/reconcile the recommended source catalog for one professional track."""
    career_track = normalize_track(career_track)
    catalog = recommended_sources_for_track(career_track)
    if not catalog:
        return 0
    kinds = {item["kind"] for item in catalog}
    identifiers = {item["identifier"] for item in catalog}
    existing_rows = db.scalars(select(Source).where(
        Source.career_track == career_track,
        Source.kind.in_(kinds),
        Source.identifier.in_(identifiers),
    ).order_by(Source.id)).all()
    existing_by_pair: dict[tuple[str, str], Source] = {}
    for source in existing_rows:
        existing_by_pair.setdefault(_source_key(source), source)

    installed = 0
    reconciled = 0
    for item in catalog:
        pair = _source_key(item)
        existing = existing_by_pair.get(pair)
        if existing is not None:
            # Keep ordinary enable/error state, but an explicit "install recommended"
            # action revives a previously retired recommended source.
            metadata = loads(existing.metadata_json, {})
            if not isinstance(metadata, dict):
                metadata = {}
            if metadata.pop("retired", None) is not None:
                metadata.pop("retired_at", None)
                metadata.setdefault("preset", "recommended")
                existing.metadata_json = dumps(metadata)
                existing.enabled = True
                reconciled += 1
            if existing.name != item["name"] or existing.company_name != item["company_name"]:
                existing.name = item["name"]
                existing.company_name = item["company_name"]
                reconciled += 1
            continue
        source = Source(**item, career_track=career_track, enabled=True, metadata_json='{"preset":"recommended"}')
        db.add(source)
        db.flush()
        existing_by_pair[pair] = source
        installed += 1

    deduped = suppress_duplicate_sources(db, career_track)
    if installed or reconciled or deduped:
        db.add(AuditLog(
            event_type="recommended_sources_installed",
            message=f"Reconciled recommended sources for {career_track}",
            details_json=dumps({"career_track": career_track, "installed": installed,
                                "reconciled": reconciled, "duplicates_suppressed": deduped}),
        ))
        db.commit()
    return installed


def recommended_source_status(db: Session, career_track: str = DEFAULT_TRACK) -> list[dict]:
    career_track = normalize_track(career_track)
    catalog = recommended_sources_for_track(career_track)
    if not catalog:
        return []
    kinds = {item["kind"] for item in catalog}
    identifiers = {item["identifier"] for item in catalog}
    existing_by_pair: dict[tuple[str, str], Source] = {}
    for source in db.scalars(select(Source).where(
        Source.career_track == career_track,
        Source.kind.in_(kinds),
        Source.identifier.in_(identifiers),
    ).order_by(Source.id)).all():
        meta = loads(source.metadata_json, {})
        if isinstance(meta, dict) and (meta.get("duplicate_of") or meta.get("retired")):
            continue
        existing_by_pair.setdefault((source.kind, source.identifier), source)
    rows: list[dict] = []
    for item in catalog:
        existing = existing_by_pair.get((item["kind"], item["identifier"]))
        rows.append({**item, "career_track": career_track, "installed": existing is not None,
                     "enabled": bool(existing.enabled) if existing else False})
    return rows
