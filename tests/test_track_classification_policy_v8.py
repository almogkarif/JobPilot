import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.services.track_classification import classify_job, reviewed_role_scope, CS
CASES=json.loads((Path(__file__).parent/'fixtures/track_classification/reviewed_v8.json').read_text())

@pytest.mark.parametrize('case',CASES,ids=lambda c:str(c['id']))
def test_reviewed_remaining_cases(case):
    result=classify_job(SimpleNamespace(title=case['title'],description=case['description']))
    assert set(result.matched_tracks)==set(case['matches']),result.to_dict()
    assert all(d.status!='review' for d in result.decisions),result.to_dict()


def test_unseen_generic_title_stays_unresolved():
    assert reviewed_role_scope('engineer','We use Python in our company and collaborate with different teams.')==(None,'')


def test_deployment_that_builds_software_is_not_excluded_by_title_alone():
    assert reviewed_role_scope('deployment engineer','Design and develop deployment automation software and APIs.')==(None,'')
