from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
JS = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")


def test_skill_suggestions_are_a_three_row_scroll_viewport():
    assert 'class="panel skill-suggestions-panel"' in HTML
    assert 'id="skill-suggestions" class="skill-suggestion-list"' in HTML
    assert '--skill-suggestion-row-height: 58px' in CSS
    assert 'max-height: calc((var(--skill-suggestion-row-height) * 3) + 16px)' in CSS
    assert 'overflow-y: auto' in CSS
    assert '.skill-suggestions-panel { align-self: start; }' in CSS


def test_skill_suggestion_rows_show_only_skill_and_job_count_copy():
    load_skills = JS[JS.index('async function loadSkills()'):JS.index('async function addSkill(')]
    assert 'class="skill-suggestion-copy"' in load_skills
    assert 'מופיע ב־${item.job_count} משרות' in load_skills
    assert 'item.jobs.map' not in load_skills
    assert '<small>' not in load_skills


def test_compact_skill_suggestion_keeps_explicit_add_action():
    load_skills = JS[JS.index('async function loadSkills()'):JS.index('async function addSkill(')]
    assert 'class="skill-suggestion-add"' in load_skills
    assert 'onclick="addSkill(' in load_skills
    assert 'aria-label="הוסף את ${esc(item.skill)} לסקילים שלי"' in load_skills
