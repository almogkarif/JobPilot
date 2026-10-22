"""Exercise CI selection against real, isolated commit histories (no app imports)."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "scripts/select_ci_tests.py"
SPEC = importlib.util.spec_from_file_location("select_ci_tests", SELECTOR)
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", *args], cwd=repo,
        stderr=subprocess.DEVNULL, text=True,
    ).strip()


def commit(repo, changes, message):
    for name, value in changes.items():
        path = repo / name
        if value is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
    git(repo, "add", "--all")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "ci-selector@example.invalid")
    git(tmp_path, "config", "user.name", "CI selector test")
    base = commit(tmp_path, {
        "AGENTS.md": "Review scope declarations.\n",
        ".github/workflows/jobpilot-tests.yml": (ROOT / ".github/workflows/jobpilot-tests.yml").read_text(),
        "app/main.py": "# initial\n",
        "app/static/app.js": "// initial\n",
    }, "Initial fixture")
    return tmp_path, base


def push(repo, base, head=None):
    return ci.select_plan(repo, {"before": base, "after": head or git(repo, "rev-parse", "HEAD")}, "push")


def targets(plan):
    return json.loads(plan["tests_json"])


def assert_full(plan):
    assert plan["scope"] == "full"
    assert targets(plan) == []
    assert plan["chromium"] == plan["postgres"] == plan["browser_agent"] == "true"
    assert plan["minimal_dependencies"] == "false"


def test_queue_selection_preserves_exact_regressions_without_database_setup(history):
    repo, base = history
    commit(repo, {"app/main.py": "# queue projection\n", "app/static/app.js": "// direct link\n"},
           "Show employer link [tests:queue]")
    plan = push(repo, base)
    assert plan["scope"] == "focused"
    assert targets(plan) == list(ci.QUEUE_TESTS)
    assert len([target for target in targets(plan) if "::" in target]) == 3
    assert plan["chromium"] == "true"
    assert plan["postgres"] == plan["browser_agent"] == plan["minimal_dependencies"] == "false"


def test_scope_union_covers_each_commit_and_deduplicates_tests(history):
    repo, base = history
    commit(repo, {"app/main.py": "# queue\n"}, "Queue [tests:queue]")
    commit(repo, {"scripts/select_ci_tests.py": "# selector\n",
                  "app/static/app.js": "// queue UI\n"}, "Select tests [tests:queue,ci]")
    commit(repo, {"app/static/index.html": "<main>Small UI change</main>"}, "UI [tests:ui]")
    plan = push(repo, base)
    assert plan["scope"] == "focused"
    assert set(targets(plan)) == set(ci.QUEUE_TESTS + ci.UI_TESTS + ci.PRESET_TESTS["ci"])
    assert len(targets(plan)) == len(set(targets(plan)))
    assert plan["minimal_dependencies"] == "false"
    assert plan["chromium"] == "true" and plan["postgres"] == "false"


def test_ci_only_uses_pytest_without_application_browser_or_postgres_dependencies(history):
    repo, base = history
    commit(repo, {"scripts/select_ci_tests.py": "# selector\n",
                  "tests/test_ci_test_selection.py": "# selector tests\n"}, "CI [tests:ci]")
    plan = push(repo, base)
    assert plan["scope"] == "focused"
    assert targets(plan) == ["tests/test_ci_test_selection.py"]
    assert plan["minimal_dependencies"] == "true"
    assert plan["chromium"] == plan["postgres"] == plan["browser_agent"] == "false"


def test_queue_gstat_and_ci_release_union_runs_exact_selected_regressions(history):
    repo, base = history
    commit(repo, {"app/main.py": "# queue\n", "agent/gstat.py": "# GSTAT form\n",
                  "tests/test_gstat_submission.py": "# GSTAT regression\n",
                  "scripts/select_ci_tests.py": "# selector\n"},
           "Queue and GSTAT [tests:queue,gstat,ci]")
    plan = push(repo, base)
    assert plan["scope"] == "focused"
    assert set(targets(plan)) == set(ci.QUEUE_TESTS + ci.PRESET_TESTS["gstat"] + ci.PRESET_TESTS["ci"])
    assert len(targets(plan)) == len(set(targets(plan)))
    assert plan["chromium"] == "true"
    assert plan["postgres"] == plan["browser_agent"] == plan["minimal_dependencies"] == "false"


def test_gstat_preset_cannot_cover_other_employer_adapters(history):
    repo, base = history
    commit(repo, {"agent/ness.py": "# unrelated employer\n"}, "Employer [tests:gstat]")
    assert_full(push(repo, base))


def test_head_marker_does_not_hide_earlier_unmarked_code_commit(history):
    repo, base = history
    commit(repo, {"app/main.py": "# earlier code\n"}, "Unreviewed change")
    commit(repo, {"app/static/app.js": "// reviewed queue\n"}, "Queue [tests:queue]")
    assert_full(push(repo, base))


def test_later_marker_cannot_cover_previous_commit_with_wrong_declared_scope(history):
    repo, base = history
    commit(repo, {"app/main.py": "# backend queue\n"}, "Wrong marker [tests:ui]")
    commit(repo, {"app/static/app.js": "// queue\n"}, "Queue [tests:queue]")
    assert_full(push(repo, base))


@pytest.mark.parametrize("message", [
    "No marker", "[tests:unknown]", "[tests:queue,unknown]", "[tests:queue,]",
    "[tests: queue]", "[tests:queue", "[tests:queue] [tests:ci,]", "[tests:full]",
    "[tests:queue] [Tests:ui]", "[tests:queue] [tests :ui]",
])
def test_unknown_missing_and_malformed_markers_fail_closed(history, message):
    repo, base = history
    commit(repo, {"app/main.py": "# changed\n"}, message)
    assert_full(push(repo, base))


@pytest.mark.parametrize("path", [
    "app/models.py", "app/database.py", "tests/conftest.py", "requirements.txt",
    "app/services/application_submission.py", "tests/test_new_unknown_queue_behavior.py",
])
def test_unknown_and_shared_paths_cannot_use_queue_marker(history, path):
    repo, base = history
    commit(repo, {path: "# broad change\n"}, "Queue [tests:queue]")
    assert_full(push(repo, base))


def test_test_only_scope_requires_known_tests_and_runs_corresponding_targets(history):
    repo, base = history
    commit(repo, {"tests/test_personal_queue_ui.py": "# meaningful queue regression\n"},
           "Queue regression [tests:queue]")
    assert "tests/test_personal_queue_ui.py" in targets(push(repo, base))


@pytest.mark.parametrize("base_value", [None, "", "0" * 40, "f" * 40, "HEAD~1", "--all"])
def test_missing_zero_unavailable_or_nonliteral_base_fails_closed(history, base_value):
    repo, _ = history
    commit(repo, {"app/main.py": "# queue\n"}, "Queue [tests:queue]")
    assert_full(push(repo, base_value))


@pytest.mark.parametrize("head_value", [None, "0" * 40, "f" * 40])
def test_missing_or_unavailable_head_fails_closed(history, head_value):
    repo, base = history
    assert_full(ci.select_plan(repo, {"before": base, "after": head_value}, "push"))


@pytest.mark.parametrize("operation", ["delete", "rename"])
def test_deletion_and_rename_never_bypass_path_validation(history, operation):
    repo, base = history
    changes = {"app/static/app.js": None}
    if operation == "rename":
        changes["app/static/styles.css"] = "// initial\n"
    commit(repo, changes, "UI change [tests:ui]")
    assert_full(push(repo, base))


def test_even_documentation_deletions_fail_closed(history):
    repo, base = history
    commit(repo, {"AGENTS.md": None}, "Remove instructions")
    assert_full(push(repo, base))


def test_documentation_only_and_interleaved_doc_commits_need_no_marker(history):
    repo, base = history
    commit(repo, {"docs/notes.md": "Updated documentation.\n",
                  "README.md": "Project documentation.\n",
                  "CONTRIBUTING.md": "Contributor guide.\n"}, "Explain behavior")
    doc_plan = push(repo, base)
    assert doc_plan["scope"] == "docs" and targets(doc_plan) == []
    assert all(doc_plan[key] == "false" for key in
               ("chromium", "postgres", "browser_agent", "minimal_dependencies"))
    commit(repo, {"app/main.py": "# queue\n", "docs/notes.md": "Queue behavior.\n"},
           "Queue and docs [tests:queue]")
    commit(repo, {"nested/AGENTS.md": "Local instructions.\n"}, "Document local rules")
    assert push(repo, base)["scope"] == "focused"


def test_pr_uses_merge_base_and_excludes_unrelated_base_branch_commits(history):
    repo, base = history
    git(repo, "checkout", "-q", "-b", "feature")
    head = commit(repo, {"app/main.py": "# queue\n"}, "Queue [tests:queue]")
    git(repo, "checkout", "-q", "-b", "base-advanced", base)
    advanced_base = commit(repo, {"app/models.py": "# unrelated base change\n"}, "Unrelated change")
    plan = ci.select_plan(repo, {"pull_request": {
        "base": {"sha": advanced_base}, "head": {"sha": head},
    }}, "pull_request")
    assert plan["scope"] == "focused" and targets(plan) == list(ci.QUEUE_TESTS)
    assert_full(push(repo, advanced_base, head))  # A non-ancestor push is different.


def test_pr_checks_every_feature_commit_not_only_head(history):
    repo, base = history
    commit(repo, {"app/models.py": "# broad\n"}, "Unmarked model change")
    head = commit(repo, {"app/main.py": "# queue\n"}, "Queue [tests:queue]")
    assert_full(ci.select_plan(repo, {"pull_request": {
        "base": {"sha": base}, "head": {"sha": head},
    }}, "pull_request"))


def test_merge_commit_fails_closed_instead_of_ignoring_resolution_changes(history):
    repo, base = history
    git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, {"app/static/app.js": "// queue\n"}, "Queue [tests:queue]")
    git(repo, "checkout", "-q", "-b", "other", base)
    commit(repo, {"docs/other.md": "Other docs.\n"}, "Docs")
    git(repo, "merge", "--no-ff", "feature", "-m", "Merge [tests:queue]")
    assert_full(push(repo, base))


def test_exceptionally_large_ranges_fail_closed_without_visiting_each_commit(history, monkeypatch):
    repo, base = history
    for index in range(3):
        commit(repo, {"app/main.py": f"# queue {index}\n"}, "Queue [tests:queue]")
    monkeypatch.setattr(ci, "MAX_COMMITS", 2)
    plan = push(repo, base)
    assert_full(plan)
    assert plan["reason"] == "oversized_range"


@pytest.mark.parametrize("scope", sorted(ci.LEGACY_SCOPES | {"full"}))
def test_manual_legacy_scopes_preserve_existing_job_routes(scope, tmp_path):
    plan = ci.select_plan(tmp_path, {"inputs": {"test_scope": scope}}, "workflow_dispatch")
    assert plan["scope"] == scope and targets(plan) == []
    assert plan["browser_agent"] == str(scope in {"full", "applications"}).lower()
    assert plan["minimal_dependencies"] == "false"
    assert plan["chromium"] == plan["postgres"] == str(scope not in {"ranking", "user_limit"}).lower()


@pytest.mark.parametrize("scope", sorted(ci.PRESET_TESTS))
def test_manual_presets_do_not_need_git_range(scope, tmp_path):
    plan = ci.select_plan(tmp_path, {"inputs": {"test_scope": scope}}, "workflow_dispatch")
    assert plan["scope"] == "focused" and targets(plan) == list(ci.PRESET_TESTS[scope])
    assert plan["minimal_dependencies"] == str(scope == "ci").lower()
    assert plan["chromium"] == str(scope != "ci").lower()
    assert plan["postgres"] == plan["browser_agent"] == "false"


@pytest.mark.parametrize("scope", ["auto", "unknown", "queue,ci", ""])
def test_manual_auto_without_reliable_range_and_unknown_scope_fail_closed(tmp_path, scope):
    assert_full(ci.select_plan(tmp_path, {"inputs": {"test_scope": scope}}, "workflow_dispatch"))


@pytest.mark.parametrize(("scope", "path"), [
    ("user_limit", "app/config.py"), ("ranking", "app/services/ranking/skills.py"),
    ("ranking", "app/services/matching.py"), ("applications", "agent/fields.py"),
    ("comeet", "agent/browser.py"), ("solaredge", "agent/run_agent.py"),
    ("scan_resources", "app/collectors/example.py"),
    ("scan_resources", "app/services/unified_catalog.py"),
    ("catalog_inventory", "app/services/source_catalog.py"),
])
def test_reviewed_legacy_subsystem_marker_routes_to_existing_job(history, scope, path):
    repo, base = history
    commit(repo, {path: "# reviewed subsystem change\n"}, f"Fix subsystem [tests:{scope}]")
    plan = push(repo, base)
    assert plan["scope"] == scope and targets(plan) == []


def test_legacy_test_allowlist_follows_existing_workflow_targets(history):
    repo, base = history
    commit(repo, {"tests/test_matching.py": "# matching regression\n"}, "Matching [tests:ranking]")
    assert push(repo, base)["scope"] == "ranking"
    commit(repo, {"tests/test_ranking_unlisted.py": "# new test not in existing job\n"},
           "New regression [tests:ranking]")
    assert_full(push(repo, base))


@pytest.mark.parametrize("marker", ["ranking,ci", "queue,applications", "ranking,scan_resources"])
def test_mixed_legacy_scopes_fall_back_to_full(history, marker):
    repo, base = history
    commit(repo, {"app/main.py": "# changed\n"}, f"Mixed change [tests:{marker}]")
    assert_full(push(repo, base))


def test_legacy_scope_cannot_hide_shared_models_or_other_subsystem(history):
    repo, base = history
    commit(repo, {"app/models.py": "# shared schema\n"}, "Ranking [tests:ranking]")
    assert_full(push(repo, base))


def test_presets_reference_existing_tests_and_legacy_steps_are_parseable():
    for tests in ci.PRESET_TESTS.values():
        for target in tests:
            path, _, node = target.partition("::")
            assert (ROOT / path).is_file(), target
            if node:
                assert f"def {node}(" in (ROOT / path).read_text(), target
    for scope in ci.LEGACY_SCOPES:
        assert ci._legacy_test_paths(ROOT, scope)


def test_workflow_uses_selection_for_automatic_full_browser_and_resource_setup():
    workflow = (ROOT / ".github/workflows/jobpilot-tests.yml").read_text()
    assert 'scripts/select_ci_tests.py' in workflow
    assert 'fetch-depth: 0' in workflow
    assert "github.event_name != 'workflow_dispatch'" not in workflow
    assert "github.event_name == 'push'" not in workflow
    assert "github.event_name == 'pull_request'" not in workflow
    assert "if: ${{ needs.select-tests.outputs.scope == 'full' }}" in workflow
    assert "if: ${{ needs.select-tests.outputs.scope == 'focused' }}" in workflow
    assert "if: ${{ needs.select-tests.outputs.scope == 'docs' }}" in workflow
    browser_job = workflow.split('\n  browser-agent:', 1)[1].split('\n  user-limit:', 1)[0]
    assert "if: ${{ needs.select-tests.outputs.browser_agent == 'true' }}" in browser_job
    main_job = workflow.split('\n  test:', 1)[1].split('\n  browser-agent:', 1)[0]
    assert "- name: Install Chromium\n        if: ${{ needs.select-tests.outputs.chromium == 'true' }}" in main_job
    assert "- name: Enable local PostgreSQL integration tests\n        if: ${{ needs.select-tests.outputs.postgres == 'true' }}" in main_job
    assert "minimal_dependencies != 'true'" in main_job
    assert "minimal_dependencies == 'true'" in main_job
    assert 'python -m pip install pytest==9.1.1 pytest-xdist==3.8.0' in main_job
    for scope in ci.LEGACY_SCOPES:
        assert f"needs.select-tests.outputs.scope == '{scope}'" in workflow
    for scope in ('auto', *sorted(ci.PRESET_TESTS), 'full', *sorted(ci.LEGACY_SCOPES)):
        assert f'          - {scope}\n' in workflow


def test_cli_writes_bounded_outputs_and_summary_without_application_imports(history, monkeypatch):
    repo, base = history
    head = commit(repo, {"scripts/select_ci_tests.py": "# selector\n"}, "CI [tests:ci]")
    event_path, output_path, summary_path = [repo / name for name in ("event.json", "output", "summary")]
    event_path.write_text(json.dumps({"before": base, "after": head}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    result = subprocess.run([
        sys.executable, "-S", str(SELECTOR), "--event-path", str(event_path),
        "--output", str(output_path), "--summary", str(summary_path),
    ], cwd=repo, env=os.environ.copy(), capture_output=True, text=True, check=True)
    plan = json.loads(result.stdout)
    outputs = dict(line.split("=", 1) for line in output_path.read_text().splitlines())
    assert outputs == plan and plan["scope"] == "focused"
    assert plan["minimal_dependencies"] == "true"
    assert len(result.stdout) < 8192 and len(summary_path.read_bytes()) < 8192
    assert "tests/test_ci_test_selection.py" in summary_path.read_text()
    assert not result.stderr


@pytest.mark.parametrize("event", [None, [], {}, {"inputs": []}])
def test_invalid_event_context_never_skips_ci(tmp_path, event):
    assert_full(ci.select_plan(tmp_path, event, "unknown"))
