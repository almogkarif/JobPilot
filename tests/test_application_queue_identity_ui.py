"""Execute queue card renderers against distinct application/job identities."""
import json
from pathlib import Path
import subprocess

import pytest


JS_PATH = Path(__file__).resolve().parents[1] / 'app/static/app.js'


def _function(source, name):
    marker = f'function {name}('
    if marker not in source:
        return ''
    start = source.index(marker)
    first_line = source[start:source.index('\n', start)]
    return first_line if first_line.endswith('}') else source[start:source.index('\n}', start) + 2]


def render_cards(identity=None, *, title='Legal Operations Specialist', company='Exodigo'):
    source = JS_PATH.read_text()
    escaping = source[source.index('const esc ='):source.index('\n\n', source.index('const esc ='))]
    functions = '\n'.join(_function(source, name) for name in (
        'autoQueueJobIdentityMarkup', 'autoQueueRowActions', 'autoQueueRunningMarkup',
        'autoQueueWaitingMarkup', 'autoQueueAttentionMarkup', 'blockerChoiceOptions',
        'blockerChoiceControlMarkup', 'questionWaitSeconds', 'questionWaitCopy', 'questionWaitMarkup',
    ))
    item = {'id': 7431, 'mode': 'auto',
            'blocker': {'id': 11, 'kind': 'choice_required', 'question': 'Approved answer?',
                        'options': ['Yes', 'No']}, **(identity or {})}
    item['job'] = {'title': title, 'company': company, **(item.get('job') or {})}
    script = '''
      const vm = require('node:vm'), fs = require('node:fs');
      const input = JSON.parse(fs.readFileSync(0, 'utf8'));
      const context = {
        applicationsWorkspaceAllowed: () => true, technicalDetailsAllowed: () => false,
        professionalMessage: value => String(value || ''), applicationTextAnswerDrafts: new Map(),
      };
      vm.createContext(context);
      vm.runInContext("const CHOICE_BLOCKER_KINDS = new Set(['choice_required','unknown_field','missing_profile_detail']);\\n" + input.source,
                      context, {timeout: 1000});
      const item = input.item;
      process.stdout.write(JSON.stringify({
        running: context.autoQueueRunningMarkup({...item, status:'applying'}, 0, 1),
        waiting: context.autoQueueWaitingMarkup({...item, status:'queued'}, 0, 0),
        attention: context.autoQueueAttentionMarkup({...item, status:'needs_input'}),
      }));
    '''
    result = subprocess.run(['node', '-e', script],
                            input=json.dumps({'source': escaping + '\n' + functions, 'item': item}),
                            text=True, capture_output=True, check=True, timeout=5)
    return json.loads(result.stdout)


@pytest.mark.parametrize('identity', [
    {'job_id': 2824},
    {'job': {'id': 2824}},
    {'job_id': '2824'},
    {'job_id': 2824, 'job': {'id': 99}},
])
def test_every_queue_card_shows_the_real_job_id_from_full_or_compact_payload(identity):
    cards = render_cards(identity)
    for markup in cards.values():
        assert 'משרה #2824' in markup
        assert 'משרה #7431' not in markup
        assert 'Legal Operations Specialist' in markup
        assert 'Exodigo' in markup
        # Opening/cancelling still address the application, not the displayed job.
        assert 'openAutoQueueApplication(7431)' in markup
        assert 'cancelAutoQueueApplication(7431)' in markup
    assert 'data-choice-application="7431"' in cards['attention']
    assert 'data-choice-answer="No"' in cards['attention']


@pytest.mark.parametrize('job_id', [None, 0, -1, 1.5, True, '', 'unknown',
                                   '<img src=x onerror=alert(1)>', '9007199254740993'])
def test_missing_or_invalid_job_id_never_uses_the_application_id_or_shows_zero(job_id):
    for markup in render_cards({'job_id': job_id}).values():
        assert 'משרה #' not in markup
        assert 'Legal Operations Specialist' in markup
        assert 'openAutoQueueApplication(7431)' in markup
        assert '<img' not in markup


def test_queue_identity_does_not_change_title_company_or_answer_escaping():
    cards = render_cards({'job': {'id': 2824}, 'blocker': {
        'id': 11, 'kind': 'choice_required', 'question': '<b>Approved answer?</b>',
        'options': ['<img src=x onerror=bad()>', 'No'],
    }}, title='<script>role</script>', company='A & B')
    for markup in cards.values():
        assert 'משרה #2824' in markup
        assert '&lt;script&gt;role&lt;/script&gt;' in markup
        assert '<script>' not in markup
        assert 'A &amp; B' in markup
        assert '<img' not in markup
    assert 'data-choice-answer="&lt;img src=x onerror=bad()&gt;"' in cards['attention']
