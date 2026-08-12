from __future__ import annotations

import httpx

from ..config import settings


def dispatch_scan_workflow(mode: str = "queued") -> None:
    token = str(settings.github_actions_token or "").strip()
    repository = str(settings.github_repository or "").strip().strip("/")
    workflow = str(settings.github_scan_workflow or "jobpilot-scan.yml").strip()
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
        json={"ref": ref, "inputs": {"mode": mode}},
        timeout=12.0,
    )
    if response.status_code < 200 or response.status_code >= 300:
        body = response.text[:500]
        raise RuntimeError(f"GitHub Actions dispatch failed ({response.status_code}): {body}")
