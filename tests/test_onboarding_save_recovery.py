"""Execute onboarding helpers against synthetic state; no network or catalog reads."""
import subprocess
from pathlib import Path

JS = Path('app/static/app.js').read_text()


def helper(name):
    start = JS.index(f'function {name}(')
    end = JS.index('\n}', start) + 2
    # Some helpers are deliberately a single line.
    first_line = JS[start:JS.index('\n', start)]
    return first_line if first_line.endswith('}') else JS[start:end]


def test_onboarding_helpers_recover_saves_deduplicate_and_scope_greeting():
    script = """
const assert=require('node:assert/strict');
const onboardingState={saveChain:Promise.resolve(),selectedSkills:new Set(['python','Python',' custom ','CUSTOM'])};
const authState={user:{email:'other@example.com'}};
const onboardingPresetSkills=()=>['Python','Java'];
let calls=0;
const api=async()=>{if(++calls===1)throw Error('Internal Server Error');return {skills:['Python']}};
const toast=()=>{};
const onboardingSyncSavedProfile=()=>{};
let buttons=[];
const $$=()=>buttons;
function button(value,selected){
  const classes=new Set(selected?['selected']:[]);
  return {dataset:{obChoice:'location',value:encodeURIComponent(value)},classList:{
    contains:x=>classes.has(x),remove:x=>classes.delete(x),
    toggle:x=>classes.has(x)?classes.delete(x):classes.add(x)
  }};
}
"""
    script += '\n'.join(helper(name) for name in (
        'onboardingPersistProfile', 'onboardingNormalizeSkills', 'onboardingSkillValues',
        'onboardingToggleChoice', 'onboardingRoyalUser',
    ))
    script += """
(async()=>{
  await assert.rejects(onboardingPersistProfile({skills:['Python']}));
  assert.deepEqual(await onboardingPersistProfile({skills:['Python']}),{skills:['Python']});
  assert.equal(calls,2);
  assert.deepEqual(onboardingSkillValues(),['Python','Java','custom']);
  assert.deepEqual([...onboardingState.selectedSkills],['Python','custom']);
  buttons=[button('Israel',false),button('Haifa',true),button('Tel Aviv',true)];
  onboardingToggleChoice(buttons[0]);
  assert.deepEqual(buttons.map(b=>b.classList.contains('selected')),[true,false,false]);
  onboardingToggleChoice(buttons[1]);
  assert.deepEqual(buttons.map(b=>b.classList.contains('selected')),[false,true,false]);
  onboardingToggleChoice(buttons[2]);
  assert.deepEqual(buttons.map(b=>b.classList.contains('selected')),[false,true,true]);
  assert.equal(onboardingRoyalUser(),false);
  authState.user.email=' YORAMP4@gmail.com ';
  assert.equal(onboardingRoyalUser(),true);
  authState.user.email='yoramp4+other@gmail.com';
  assert.equal(onboardingRoyalUser(),false);
  authState.user=null;
  assert.equal(onboardingRoyalUser(),false);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(['node', '-e', script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_new_cloud_user_can_save_onboarding_preferences(monkeypatch):
    from fastapi.testclient import TestClient
    import app.auth as auth_module
    import app.main as main_module
    from app.auth import AuthIdentity
    from app.config import settings

    monkeypatch.setattr(settings, 'auth_mode', 'supabase')
    monkeypatch.setattr(settings, 'owner_email', 'owner@example.com')
    monkeypatch.setattr(settings, 'allowed_emails', '')
    monkeypatch.setattr(settings, 'storage_mode', 'local')
    monkeypatch.setattr(auth_module, 'verify_supabase_token',
                        lambda token: AuthIdentity('onboarding-new-user', 'new-onboarding@example.com', 'google'))
    # Check the request transaction without dispatching ranking or application work.
    queued = []
    monkeypatch.setattr(main_module, '_queue_profile_derived_refresh', lambda *args: queued.append(args))
    headers = {'Authorization': 'Bearer onboarding-test'}
    with TestClient(main_module.app) as client:
        response = client.get('/api/profile', headers=headers)
        assert response.status_code == 200, response.text
        for seniority in (['junior'], ['junior', 'unknown']):
            response = client.patch('/api/profile', headers=headers, json={
                'desired_titles': ['software engineer'], 'preferred_locations': ['Israel'],
                'years_experience_options': ['0'], 'degree_level': 'bachelor',
                'preferred_work_modes': ['hybrid', 'remote', 'onsite'],
                'seniority_levels': seniority, 'keywords': [], 'excluded_keywords': [],
            })
            assert response.status_code == 200, response.text
            assert response.json()['seniority_levels'] == seniority
        assert queued
