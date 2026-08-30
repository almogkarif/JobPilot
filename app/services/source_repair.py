from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, Source
from ..utils import dumps


@dataclass(frozen=True)
class SourceMigration:
    kind: str
    identifier: str
    reason: str


# These sources used to be scraped through their public HTML careers page. Their
# underlying ATS is more stable and exposes the same public vacancies as structured
# data, so migrate existing installations instead of keeping brittle DOM selectors.
ATS_MIGRATIONS: dict[str, SourceMigration] = {
    "applied-materials": SourceMigration(
        kind="workday",
        identifier="applied-materials",
        reason="migrated from rendered careers HTML to the official Workday board",
    ),
    "similarweb": SourceMigration(
        kind="greenhouse",
        identifier="similarweb",
        reason="the old careers.similarweb.com board is retired; Similarweb publishes through Greenhouse",
    ),
    "outbrain": SourceMigration(
        kind="greenhouse",
        identifier="outbraininc",
        reason="migrated to Outbrain's EU Greenhouse board",
    ),
    "cyberark": SourceMigration(
        kind="smartrecruiters",
        identifier="Cyberark1",
        reason="migrated to CyberArk's public SmartRecruiters Posting API",
    ),
    "checkpoint": SourceMigration(
        kind="smartrecruiters",
        identifier="CheckPointSoftwareTechnologies2",
        reason="migrated to Check Point's public SmartRecruiters Posting API",
    ),
    "appsflyer": SourceMigration(
        kind="greenhouse",
        identifier="appsflyer",
        reason="migrated from branded careers HTML to AppsFlyer's public Greenhouse board",
    ),
    "cato": SourceMigration(
        kind="greenhouse",
        identifier="catonetworks",
        reason="migrated from branded careers HTML to Cato Networks' public Greenhouse board",
    ),
    "wiz": SourceMigration(
        kind="greenhouse",
        identifier="wizinc",
        reason="migrated from branded careers HTML to Wiz's public Greenhouse board",
    ),
    "sentinelone": SourceMigration(
        kind="greenhouse",
        identifier="sentinellabs",
        reason="migrated from branded careers HTML to SentinelOne's public Greenhouse board",
    ),
    "connecteam": SourceMigration(
        kind="greenhouse",
        identifier="connecteam",
        reason="migrated from branded careers HTML to Connecteam's public Greenhouse board",
    ),
    "mobileye": SourceMigration(
        kind="lever",
        identifier="eu:mobileye",
        reason="migrated from rendered careers HTML to Mobileye's structured EU Lever board",
    ),
    "taboola": SourceMigration(
        kind="greenhouse",
        identifier="taboola",
        reason="migrated from rendered careers HTML to Taboola's structured Greenhouse board",
    ),
    "orca": SourceMigration(
        kind="greenhouse",
        identifier="orcasecurity",
        reason="migrated from rendered careers HTML to Orca Security's structured Greenhouse board",
    ),
}

# Official-page sources whose URL/selector was refreshed in v0.1.13. Keeping this
# explicit prevents unrelated user-created sources from being retried unexpectedly.
REFRESHED_OFFICIAL_IDENTIFIERS = {
    "checkpoint",
    "wix",
    "ibm",
    "salesforce",
    "meta",
    "philips",
    "elbit",
    "rafael",
    "iai",
    "appsflyer",
    "aqua",
}


def repair_error_sources(db: Session) -> dict:
    """Migrate fragile known sources and prepare failed sources for a targeted retry.

    Structured ATS migrations are applied even when a legacy HTML collector happened
    to report success: malformed HTML can return plausible-but-wrong rows without
    setting ``last_error``. Other refreshed official sources are retried only when
    they currently carry an error. Errors remain visible until the retry succeeds.
    """
    sources = db.scalars(
        select(Source).where(
            Source.enabled.is_(True),
            Source.kind != "demo",
        )
    ).all()

    retry_ids: list[int] = []
    migrated: list[dict[str, str | int]] = []
    refreshed: list[dict[str, str | int]] = []
    normalized_health: list[int] = []

    migration_targets = {(item.kind, item.identifier) for item in ATS_MIGRATIONS.values()}

    for source in sources:
        # Older builds used 88% for a successful source that simply had no matching
        # Israel jobs. Health now measures collector/data quality only, not job count.
        if not source.last_error and (int(source.health_score or 0) < 100 or int(source.consecutive_failures or 0) != 0):
            source.health_score = 100
            source.consecutive_failures = 0
            normalized_health.append(source.id)

        old_kind = source.kind
        old_identifier = source.identifier
        migration = ATS_MIGRATIONS.get(old_identifier) if old_kind == "official_careers" else None

        # Always replace these legacy rendered-page collectors with their public ATS.
        # This also catches sources that returned corrupt data without throwing.
        if migration:
            source.kind = migration.kind
            source.identifier = migration.identifier
            source.disabled_until = None
            retry_ids.append(source.id)
            migrated.append({
                "id": source.id,
                "name": source.name,
                "from": f"{old_kind}:{old_identifier}",
                "to": f"{source.kind}:{source.identifier}",
                "reason": migration.reason,
            })
            continue

        # If a migrated source still has an error (for example startup was interrupted),
        # retry it on the next launch. Healthy migrated sources are left alone.
        if (old_kind, old_identifier) in migration_targets and source.last_error:
            source.disabled_until = None
            retry_ids.append(source.id)
            refreshed.append({
                "id": source.id,
                "name": source.name,
                "source": f"{old_kind}:{old_identifier}",
            })
            continue

        if source.last_error and old_kind == "official_careers" and old_identifier in REFRESHED_OFFICIAL_IDENTIFIERS:
            source.disabled_until = None
            retry_ids.append(source.id)
            refreshed.append({
                "id": source.id,
                "name": source.name,
                "source": f"{old_kind}:{old_identifier}",
            })

    retry_ids = list(dict.fromkeys(retry_ids))
    if retry_ids or normalized_health:
        db.add(AuditLog(
            event_type="errored_sources_repaired",
            message=f"Prepared {len(retry_ids)} repaired sources for targeted retry",
            details_json=dumps({
                "source_ids": retry_ids,
                "migrated": migrated,
                "refreshed_official": refreshed,
                "normalized_health": normalized_health,
            }),
        ))
        db.commit()

    return {
        "source_ids": retry_ids,
        "migrated": migrated,
        "refreshed_official": refreshed,
        "normalized_health": normalized_health,
    }
