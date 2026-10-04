"""Guest browser startup and cards, using a disposable local server only."""
import time

import pytest
from playwright.sync_api import expect

from tests.test_mobile_ui import mobile_server, phone


@pytest.mark.parametrize('shared_scores', [False, True])
def test_guest_bootstrap_shows_catalog_without_personal_loading_requests(phone, mobile_server, shared_scores):
    page, work = phone
    base, _ = mobile_server
    dashboard = page.request.get(base + '/api/dashboard').json()
    jobs = dashboard['recent_jobs']
    for job in jobs:
        job.update(guest_catalog=True, guest_match_available=shared_scores,
                   ranking_pending=False, score=90 if shared_scores else 0, status='new', application_id=None)
    dashboard.update(guest_catalog=True, ranking_pending_jobs=0, ranking_refresh={'running': False},
                     guest_matches_available=shared_scores,
                     strong_matches=len(jobs) if shared_scores else 0, queued=0, submitted=0, needs_input=0,
                     auto_apply_queue={'current': None, 'waiting': [], 'waiting_count': 0, 'queued_count': 0, 'total_active_count': 0},
                     scan_suggestions=[dict(jobs[0], score=85 if shared_scores else None)], open_blockers=0)
    page.route('**/api/auth/config', lambda route: route.fulfill(json={
        'mode': 'supabase', 'supabase_url': 'https://auth.invalid', 'supabase_publishable_key': 'test',
    }))
    page.route('**/api/auth/me', lambda route: route.fulfill(json={
        'user': {'is_guest': True, 'role': 'guest'},
        'capabilities': {'application_agent': False, 'developer_tools': False, 'write': False},
    }))
    page.route('**/api/dashboard', lambda route: route.fulfill(json=dashboard))
    session = {'access_token': 'synthetic-local-only', 'expires_at': time.time() + 3600}
    page.evaluate('session=>{localStorage.setItem("jobpilot-cloud-session-v1",JSON.stringify(session));localStorage.removeItem("jobpilot-active-view")}', session)
    requested = []
    page.on('request', lambda request: requested.append(request.url.split(base)[-1]))
    page.reload(wait_until='networkidle')
    expect(page.locator('#guest-mode-banner')).to_be_visible()
    expect(page.locator('#daily-recommendations-title')).to_have_text('התאמות בפרופיל ההדגמה' if shared_scores else 'משרות מהקטלוג החי')
    expect(page.locator('#recommendations-ranking-status')).to_be_hidden()
    assert page.locator('#recent-jobs .is-pending').count() == 0
    assert ('90% בהדגמה' in page.locator('#recent-jobs').inner_text()) is shared_scores
    assert page.locator('#scan-suggestions .scan-suggestion-card').count() == 1
    assert page.locator('#scan-suggestions .scan-suggestion-score').count() == int(shared_scores)
    assert page.locator('#metrics .metric').count() == (3 if shared_scores else 1)
    assert not any(path.split('?')[0] in {
        '/api/profile', '/api/resumes', '/api/answer-library', '/api/ranking/refresh', '/api/agent/status',
    } for path in requested), requested
    # Opening a guest profile reads only its own harmless preferences, no CV/answers.
    requested.clear()
    page.evaluate('loadProfile()')
    assert '/api/profile' in requested
    assert '/api/resumes' not in requested and '/api/answer-library' not in requested
    explanation = page.evaluate('job=>renderV2RankingExplanation(job)', jobs[0])
    assert 'לאחר התחברות' in explanation and 'הדירוג מתעדכן' not in explanation
    assert ('פרטי הפרופיל ופירוט ההתאמה פרטיים' in explanation) is shared_scores
    page.route(f'**/api/jobs/{jobs[0]["id"]}', lambda route: route.fulfill(json=dict(jobs[0], description='Public job description')))
    requested.clear()
    page.evaluate('id=>showJob(id)', jobs[0]['id'])
    assert not any('/api/resumes' in path for path in requested)
    page.evaluate('closeModal()')
    page.screenshot(path=str(work / f'guest-dashboard-{shared_scores}.png'), full_page=True)
