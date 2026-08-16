from pathlib import Path
from types import SimpleNamespace
from app import main

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/static/app.js").read_text()
HTML = (ROOT / "app/static/index.html").read_text()

def test_corrected_onboarding_generation_forces_one_clean_rerun():
    assert main.ONBOARDING_VERSION == 2
    assert "const ONBOARDING_VERSION = 2" in JS
    assert "app.js?v=0.29.6" in HTML

def test_developer_tools_are_server_authorized(monkeypatch):
    monkeypatch.setattr(main.settings, "auth_mode", "supabase")
    monkeypatch.setattr(main.settings, "owner_email", "owner@example.com")
    monkeypatch.setattr(main.settings, "application_agent_owner_email", "")
    owner = SimpleNamespace(email="OWNER@example.com", role="user", is_guest=False)
    regular = SimpleNamespace(email="friend@example.com", role="user", is_guest=False)
    assert main._developer_tools_allowed(owner) is True
    assert main._developer_tools_allowed(regular) is False

def test_frontend_uses_developer_capability_not_only_role():
    assert "authState.capabilities?.developer_tools === true" in JS
    assert 'id="developer-runtime-status"' in HTML
