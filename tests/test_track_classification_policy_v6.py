"""Role boundaries agreed after the v5 comparison."""
from types import SimpleNamespace
import pytest
from app.services.track_classification import classify_job, CS, EE, IE

BODY='Work with colleagues to deliver reliable results, investigate requirements and document the outcome of the work. '

@pytest.mark.parametrize('title,description,expected', [
 ('RT Embedded Engineer','Develop embedded software for real time systems.',(CS,EE)),
 ('Malware Researcher','Research malicious code and develop detection tools in Python.',(CS,)),
 ('Vulnerability Researcher','Reverse engineering and C programming to research software vulnerabilities.',(CS,)),
 ('Technical Support Engineer','Troubleshoot software and write Python scripts. Requirements: BSc in Computer Science.',()),
 ('SOC Analyst','Monitor alerts and investigate incidents using Python.',()),
 ('IT Support Engineer','Maintain servers and networks using Python.',()),
 ('Software Product Manager','Manage software products and SaaS roadmaps.',(IE,)),
 ('Engineering Manager','Lead software developers and backend engineering teams.',(CS,)),
 ('Manual QA Engineer','Perform manual software tests for web applications.',(CS,)),
 ('DevSecOps Engineer','Develop software infrastructure and automation.',(CS,)),
 ('Field Operations','Operate equipment and perform physical field work.',(IE,)),
 ('מרכיב.ה מכאני.ת','הרכבת חלקים ומכלולים בקווי הייצור.',(IE,)),
 ('מבקר.ת איכות','בדיקת מוצרים ובקרת איכות בקווי הייצור.',(IE,)),
 ('אחראי/ת תפעול בפרויקט','מעקב ובקרה על תקציב ולוחות זמנים.',(IE,)),
 ('System Integration Engineer','Integrate hardware and electronics systems.',(EE,)),
 ('Flight Control Engineer','Develop control algorithms for flight control systems.',(CS,EE)),
 ('Malware Researcher','Research software code. Requirements: BSc in Biology required.',()),
 ('Quality Inspector','Requirements: Certified technician required.',()),
])
def test_role_boundaries(title,description,expected):
    result=classify_job(SimpleNamespace(title=title,description=BODY+description))
    assert result.matched_tracks==expected,result.to_dict()


def test_research_without_degree_is_yellow():
    result=classify_job(SimpleNamespace(title='Malware Researcher',description=BODY+'Research code and develop tools in Python.'))
    assert result.decisions[0].degree_color=='yellow'
