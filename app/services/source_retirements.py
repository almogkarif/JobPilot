"""Reviewed source exclusions; no startup repair or historical data deletion.

The reference inventory remains intact for audit/recovery. Operational lists,
installation and scans all use this policy. Removing a reviewed exclusion later
restores the same source identity and its administrator settings.
"""
from __future__ import annotations

AUDIT_RELEASE = '2026-09-27-alternatives'
RETIRED_SOURCES = {
    ('greenhouse', 'armissecurity'): 'Armis vacancies moved to the existing ServiceNow source.',
    ('smartrecruiters', 'cyberark1'): 'CyberArk vacancies moved to the existing Palo Alto Networks source.',
    # Pre-ATS installations can still retain this legacy identity.
    ('official_careers', 'cyberark'): 'CyberArk vacancies moved to the existing Palo Alto Networks source.',
    ('ashby', 'https://career.rafael.co.il/search'): 'Invalid duplicate: an employer URL is not an Ashby board.',
    ('official_careers', 'analog-devices'): 'No verified Israel vacancies on the bounded official alternatives.',
    ('official_careers', 'ashdod-port'): 'Official career pages reject automated collection.',
    ('official_careers', 'assuta'): 'Current official board requires a CAPTCHA.',
    ('official_careers', 'cal'): 'Current official listing and vacancy pages reject automated collection.',
    ('official_careers', 'cellcom'): 'No bounded verified vacancy feed on the current application.',
    ('official_careers', 'deep-instinct'): 'Current official listings expose no verified Israel vacancies.',
    ('official_careers', 'deloitte-israel'): 'Official vacancies exist but automated collection is blocked.',
    ('official_careers', 'dhl-israel'): 'Local listings lack stable per-vacancy identity.',
    ('official_careers', 'elspec'): 'Official careers page blocks automated collection.',
    ('official_careers', 'ericsson'): 'No verified Israel vacancies on the current official alternative.',
    ('official_careers', 'haifa-port'): 'Official listing and vacancy pages reject automated collection.',
    ('official_careers', 'harel'): 'Current official board exceeds the bounded response limit.',
    ('official_careers', 'ibm'): 'No verified Israel vacancies on the current official alternative.',
    ('official_careers', 'isracard'): 'Current official career board blocks automated collection.',
    ('official_careers', 'israel-post'): 'Current official board requires a CAPTCHA.',
    ('official_careers', 'israel-railways'): 'Current official board requires robot validation.',
    ('official_careers', 'jabil-israel'): 'No verified Israel vacancies on the bounded official alternatives.',
    ('official_careers', 'malam-team'): 'Current official career pages block automated collection.',
    ('official_careers', 'max'): 'No bounded verified vacancy feed on the current application.',
    ('official_careers', 'meuhedet'): 'Official marketing pages do not expose a verified vacancy feed.',
    ('official_careers', 'neuroblade'): 'Official board is unavailable and no alternative was verified.',
    ('official_careers', 'niram-gitan'): 'Current employer site has no verified public vacancy board.',
    ('official_careers', 'nokia'): 'No verified Israel vacancies on the current official alternative.',
    ('official_careers', 'orcam'): 'Official careers links are unavailable; no alternative was verified.',
    ('official_careers', 'partner'): 'Current official career routes expose no verified vacancy feed.',
    ('official_careers', 'phoenix'): 'Public vacancies exist but the current detail feed rejects automated collection.',
    ('official_careers', 'pliops'): 'Official careers page blocks automated collection.',
    ('official_careers', 'rafael'): 'Official career board blocks automated collection.',
    ('official_careers', 'rambam'): 'Inline roles lack verified per-vacancy location and application identity.',
    ('official_careers', 'scd'): 'Published roles lack distinct stable employer vacancy IDs.',
    ('official_careers', 'sheba'): 'No verified current vacancy feed in the official application.',
    ('official_careers', 'shufersal'): 'Neither current official board returned a bounded usable response.',
    ('official_careers', 'tnuva'): 'Current official pages expose security shells instead of vacancies.',
    ('official_careers', 'tower-semiconductor'): 'New official listing works but vacancy details are blocked.',
    ('official_careers', 'unilever-israel'): 'No verified Israel vacancies on the current official alternative.',
    ('official_careers', 'ups-israel'): 'No verified Israel vacancies on the current official alternative.',
    ('official_careers', 'vayyar'): 'Employer-linked board currently exposes no verified Israel vacancies.',
    ('official_careers', 'xm-cyber'): 'Employer-linked board currently exposes no verified Israel vacancies.',
}


def retirement_reason(kind, identifier):
    return RETIRED_SOURCES.get((str(kind).strip().casefold(), str(identifier).strip().rstrip('/').casefold()), '')


def available_source_condition():
    """Filter existing bounded/aggregate queries in SQL, returning no extra data."""
    from sqlalchemy import func, tuple_
    from ..models import Source
    return tuple_(func.lower(func.trim(Source.kind)),
                  func.lower(func.rtrim(func.trim(Source.identifier), '/'))).not_in(tuple(RETIRED_SOURCES))
