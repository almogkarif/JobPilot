from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, Source
from .career_tracks import COMPUTER_SCIENCE, INDUSTRIAL_ENGINEERING, DEFAULT_TRACK, normalize_track

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
)

RECOMMENDED_SOURCES_BY_TRACK = {
    COMPUTER_SCIENCE: CS_RECOMMENDED_SOURCES,
    INDUSTRIAL_ENGINEERING: IEM_RECOMMENDED_SOURCES,
}
# Backward-compatible symbol used by older tests/imports.
RECOMMENDED_SOURCES = CS_RECOMMENDED_SOURCES


def recommended_sources_for_track(career_track: str = DEFAULT_TRACK) -> tuple[dict[str, str], ...]:
    return RECOMMENDED_SOURCES_BY_TRACK[normalize_track(career_track)]


def install_recommended_sources(db: Session, career_track: str = DEFAULT_TRACK) -> int:
    """Install missing recommended sources for one professional track."""
    career_track = normalize_track(career_track)
    catalog = recommended_sources_for_track(career_track)
    if not catalog:
        return 0
    kinds = {item["kind"] for item in catalog}
    identifiers = {item["identifier"] for item in catalog}
    existing_pairs = {
        (source.kind, source.identifier)
        for source in db.scalars(select(Source).where(
            Source.career_track == career_track,
            Source.kind.in_(kinds),
            Source.identifier.in_(identifiers),
        )).all()
    }
    installed = 0
    for item in catalog:
        pair = (item["kind"], item["identifier"])
        if pair in existing_pairs:
            continue
        db.add(Source(**item, career_track=career_track, enabled=True,
                      metadata_json='{"preset":"recommended"}'))
        existing_pairs.add(pair)
        installed += 1
    if installed:
        db.add(AuditLog(
            event_type="recommended_sources_installed",
            message=f"Installed {installed} recommended sources for {career_track}",
            details_json=f'{{"career_track":"{career_track}"}}',
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
    existing_by_pair = {
        (source.kind, source.identifier): source
        for source in db.scalars(select(Source).where(
            Source.career_track == career_track,
            Source.kind.in_(kinds),
            Source.identifier.in_(identifiers),
        )).all()
    }
    rows: list[dict] = []
    for item in catalog:
        existing = existing_by_pair.get((item["kind"], item["identifier"]))
        rows.append({**item, "career_track": career_track, "installed": existing is not None,
                     "enabled": bool(existing.enabled) if existing else False})
    return rows
