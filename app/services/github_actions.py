from __future__ import annotations

import httpx

from ..config import settings


def dispatch_scan_workflow(mode: str = "queued") -> None:
    _dispatch_workflow(str(settings.github_scan_workflow or "jobpilot-scan.yml"), {"mode": mode})


def dispatch_application_workflow(application_id: int) -> None:
    _dispatch_workflow(
        str(settings.github_application_workflow or "jobpilot-application.yml"),
        {"application_id": str(application_id)},
    )


def _dispatch_workflow(workflow: str, inputs: dict[str, str]) -> None:
    token = str(settings.github_actions_token or "").strip()
    repository = str(settings.github_repository or "").strip().strip("/")
    workflow = str(workflow or "").strip()
    ref = str(settings.github_ref or "main").strip() or "main"
    if not token:
        raise RuntimeError("JOBPILOT_GITHUB_ACTIONS_TOKEN is not configured")
    if "/" not in repository:
        raise RuntimeError("JOBPILOT_GITHUB_REPOSITORY must be OWNER/REPO")
    url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/dispatches"
    response = httpx.post(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "JobPilot",
        },
        json={"ref": ref, "inputs": inputs},
        timeout=12.0,
    )
    if response.status_code < 200 or response.status_code >= 300:
        body = response.text[:500]
        raise RuntimeError(f"GitHub Actions dispatch failed ({response.status_code}): {body}")
