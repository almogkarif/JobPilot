#!/usr/bin/env python3
"""Select reviewed CI presets from every commit in a local Git event range.

Commit markers are declarations of review scope, not dependency inference. Missing
context, unsupported changes, and mixed legacy scopes deliberately run full CI.
"""

import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess


QUEUE_TESTS = (
    "tests/test_application_queue_identity_ui.py",
    "tests/test_application_tracking_access.py",
    "tests/test_auto_apply_queue_focus.py",
    "tests/test_auto_apply_queue_priority.py",
    "tests/test_application_queue_waiting_ui.py",
    "tests/test_personal_queue_ui.py",
    "tests/test_job_id_search.py",
    "tests/test_supabase_egress_optimization.py::test_personal_tracking_is_two_bounded_metadata_queries",
    "tests/test_supabase_egress_optimization.py::test_explicit_tracking_job_links_reuse_bounded_owner_scoped_metadata_reads",
    "tests/test_supabase_egress_optimization.py::test_tracking_job_link_opt_in_is_not_sticky_and_adds_no_polling",
)
UI_TESTS = tuple(f"tests/test_{name}.py" for name in (
    "mobile_ui", "mobile_logo_contract", "mobile_dock_bottom_contract",
    "dashboard_company_logo_ring", "career_theme_parity",
    "career_theme_no_blue_leaks", "career_theme_leak_seal_v3",
))
PRESET_TESTS = {
    "queue": QUEUE_TESTS,
    "ui": UI_TESTS,
    "ci": ("tests/test_ci_test_selection.py",),
    "gstat": ("tests/test_gstat_submission.py", "tests/test_gstat_queue.py"),
}
STATIC_PATHS = {
    "app/static/app.js", "app/static/styles.css", "app/static/mobile.css",
    "app/static/index.html",
}
PRESET_PATHS = {
    "queue": {"app/main.py", *STATIC_PATHS.difference({"app/static/index.html"}),
              *(target.split("::")[0] for target in QUEUE_TESTS)},
    "ui": {*STATIC_PATHS, *UI_TESTS},
    "ci": {".github/workflows/jobpilot-tests.yml", "scripts/select_ci_tests.py",
           "tests/test_ci_test_selection.py"},
    "gstat": {"agent/gstat.py", "tests/test_gstat_submission.py", "tests/test_gstat_queue.py"},
}
LEGACY_SCOPES = {
    "user_limit", "ranking", "scan_resources", "applications", "comeet",
    "solaredge", "catalog_inventory",
}
# These names identify existing workflow steps, whose exact targets remain the
# source of truth for legacy jobs. An unreadable/changed step fails closed.
LEGACY_STEPS = {
    "user_limit": "Run user-limit tests",
    "ranking": "Run ranking tests",
    "scan_resources": "Run scan and resource-budget tests",
    "applications": "Run application release tests",
    "comeet": "Run focused Comeet release tests",
    "solaredge": "Run focused SolarEdge release tests",
    "catalog_inventory": "Run catalog inventory and automatic queue release tests",
}
LEGACY_PATTERNS = {
    "user_limit": ("app/config.py", "app/auth.py"),
    "ranking": tuple(f"app/services/{name}*" for name in (
        "ranking", "matching", "resume_fit", "job_requirements", "career_tracks",
        "track_classification",
    )),
    "applications": ("agent/**", "app/application_questions.py",
                     "app/services/application*.py"),
    "comeet": ("agent/browser.py", "agent/run_agent.py", "app/services/application*.py"),
    "solaredge": ("agent/browser.py", "agent/run_agent.py", "app/services/application*.py"),
    "scan_resources": ("app/collectors/**", "app/config.py",
                       ".github/workflows/jobpilot-scan.yml", *(f"app/services/{name}*" for name in (
                           "scan", "catalog", "source", "unified", "external_scan_worker",
                           "derived_refresh", "egress",
                       ))),
}
LEGACY_PATTERNS["catalog_inventory"] = LEGACY_PATTERNS["scan_resources"]
KNOWN_SCOPES = {*PRESET_TESTS, *LEGACY_SCOPES, "full"}
SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
MARKER = re.compile(r"\[tests:([a-z_]+(?:,[a-z_]+)*)\]")
MAX_GIT_OUTPUT = 2 * 1024 * 1024
MAX_COMMITS = 200


def _plan(scope, reason, presets=()):
    tests = list(dict.fromkeys(target for preset in sorted(presets)
                               for target in PRESET_TESTS[preset]))
    chromium = scope in {"full", "applications", "comeet", "solaredge",
                         "catalog_inventory", "scan_resources"} or bool(set(presets) & {"queue", "ui", "gstat"})
    postgres = scope in {"full", "applications", "comeet", "solaredge",
                         "catalog_inventory", "scan_resources"}
    return {
        "scope": scope,
        "tests_json": json.dumps(tests, separators=(",", ":")),
        "chromium": str(chromium).lower(),
        "postgres": str(postgres).lower(),
        "minimal_dependencies": str(scope == "focused" and set(presets) == {"ci"}).lower(),
        "browser_agent": str(scope in {"full", "applications"}).lower(),
        "reason": reason,
    }


def _git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=15, check=True)
    if len(result.stdout) > MAX_GIT_OUTPUT:
        raise ValueError("Git output exceeds selection bound")
    return result.stdout.decode("utf-8", errors="strict")


def _commit_exists(repo, value):
    if not isinstance(value, str) or not SHA.fullmatch(value) or not value.strip("0"):
        return False
    _git(repo, "cat-file", "-e", f"{value}^{{commit}}")
    return True


def _declared_scopes(message):
    matches = list(MARKER.finditer(message))
    # Incomplete markers and whitespace/unknown-name variants must not disappear
    # behind an otherwise valid marker in the same message.
    if re.search(r"\[tests\b", MARKER.sub("", message), re.IGNORECASE):
        raise ValueError("Malformed test marker")
    scopes = {scope for match in matches for scope in match.group(1).split(",")}
    if not scopes.issubset(KNOWN_SCOPES):
        raise ValueError("Unknown test marker")
    return scopes


def _documentation(path):
    return path in {"AGENTS.md", "README.md", "CONTRIBUTING.md"} or path.endswith("/AGENTS.md") or (
        path.startswith("docs/") and path.endswith(".md")
    )


def _legacy_test_paths(repo, scope):
    workflow = (Path(repo) / ".github/workflows/jobpilot-tests.yml").read_text()
    heading = f"      - name: {LEGACY_STEPS[scope]}\n"
    if workflow.count(heading) != 1:
        raise ValueError("Legacy workflow step is unavailable")
    section = workflow.split(heading, 1)[1]
    # Stop before the next step or job. This intentionally recognizes only the
    # existing simple literal pytest target lists, not arbitrary YAML programs.
    section = re.split(r"\n(?:      - name:|  [a-zA-Z][\w-]*:)", section, maxsplit=1)[0]
    paths = set(re.findall(r"\btests/[a-zA-Z0-9_/]+\.py\b", section))
    if not paths:
        raise ValueError("Legacy test targets are unavailable")
    return paths


def _paths_covered(repo, paths, scopes):
    if scopes & LEGACY_SCOPES:
        if len(scopes) != 1:
            return False
        scope = next(iter(scopes))
        exact = {"app/main.py", "app/static/app.js", *_legacy_test_paths(repo, scope)}
        return all(path in exact or any(fnmatch.fnmatchcase(path, pattern)
                                       for pattern in LEGACY_PATTERNS[scope]) for path in paths)
    allowed = set().union(*(PRESET_PATHS[scope] for scope in scopes))
    return set(paths).issubset(allowed)


def select_plan(repo, event, event_name):
    """Return string-valued GitHub outputs, conservatively selecting full CI."""
    full = lambda reason: _plan("full", reason)
    try:
        if not isinstance(event, dict):
            return full("invalid_event")
        if event_name == "workflow_dispatch":
            scope = event.get("inputs", {}).get("test_scope", "auto")
            if scope in PRESET_TESTS:
                return _plan("focused", "manual_preset", (scope,))
            if scope in LEGACY_SCOPES or scope == "full":
                return _plan(scope, "manual_scope")
            # A dispatch has no reliable before/head range. Do not guess a
            # single latest commit and silently omit earlier unreleased work.
            return full("manual_auto_or_unknown_scope")
        if event_name == "push":
            base, head = event.get("before"), event.get("after")
            if not _commit_exists(repo, base) or not _commit_exists(repo, head):
                return full("missing_range")
            _git(repo, "merge-base", "--is-ancestor", base, head)
        elif event_name == "pull_request":
            pull = event.get("pull_request", {})
            base, head = pull.get("base", {}).get("sha"), pull.get("head", {}).get("sha")
            if not _commit_exists(repo, base) or not _commit_exists(repo, head):
                return full("missing_range")
            base = _git(repo, "merge-base", base, head).strip()
        else:
            return full("unknown_event")
        commits = _git(repo, "rev-list", "--reverse", f"{base}..{head}").splitlines()
        if not commits:
            return full("empty_range")
        if len(commits) > MAX_COMMITS:
            return full("oversized_range")
        combined, has_code = set(), False
        for commit in commits:
            parents = _git(repo, "rev-list", "--parents", "-n", "1", commit).split()
            if len(parents) != 2:
                return full("root_or_merge_commit")
            scopes = _declared_scopes(_git(repo, "show", "-s", "--format=%B", commit))
            if "full" in scopes:
                return full("explicit_full")
            changes = _git(repo, "diff-tree", "--no-commit-id", "--name-status",
                           "-r", "--no-renames", "-z", commit).split("\0")
            paths = []
            for index in range(0, len(changes) - 1, 2):
                status, path = changes[index:index + 2]
                if status not in {"A", "M"}:
                    return full("destructive_or_renamed_path")
                if not _documentation(path):
                    paths.append(path)
            if not paths:
                continue
            has_code = True
            if not scopes:
                return full("unmarked_code_commit")
            if not _paths_covered(repo, paths, scopes):
                return full("uncovered_paths")
            combined.update(scopes)
        if not has_code:
            return _plan("docs", "documentation_only")
        if combined & LEGACY_SCOPES:
            return (_plan(next(iter(combined)), "reviewed_legacy_range") if len(combined) == 1
                    else full("mixed_legacy_scopes"))
        return _plan("focused", "reviewed_range", combined)
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError,
            subprocess.SubprocessError):
        return full("unavailable_or_invalid_context")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--output")
    parser.add_argument("--summary")
    args = parser.parse_args()
    try:
        raw = Path(args.event_path).read_bytes()
        event = json.loads(raw) if len(raw) <= MAX_GIT_OUTPUT else None
    except (OSError, ValueError):
        event = None
    plan = select_plan(Path.cwd(), event, os.environ.get("GITHUB_EVENT_NAME", ""))
    if args.output:
        with open(args.output, "a", encoding="utf-8") as output:
            output.write("".join(f"{key}={value}\n" for key, value in plan.items()))
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as summary:
            summary.write(f"CI selection: **{plan['scope']}** ({plan['reason']}).\n\n")
            summary.write(f"Chromium: {plan['chromium']}; PostgreSQL: {plan['postgres']}; "
                          f"separate browser job: {plan['browser_agent']}.\n\n")
            summary.writelines(f"- `{target}`\n" for target in json.loads(plan["tests_json"]))
    print(json.dumps(plan, sort_keys=True))


if __name__ == "__main__":
    main()
