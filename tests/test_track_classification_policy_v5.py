"""Latest user decisions: role scope and personal degree filters stay separate."""
from types import SimpleNamespace
import pytest
from app.services.track_classification import classify_job, CS, EE, IE
from app.services.shared_source_comparison import compare_job

BASE='Coordinate work across teams, analyze requirements and deliver reliable results with stakeholders and customers.\n'

def classify(title, requirement='', body=BASE):
    return classify_job(SimpleNamespace(title=title,description=body+'\nRequirements:\n'+requirement))

@pytest.mark.parametrize('title,requirement,body,expected', [
 ('SOC Analyst','3 years experience in SOC and SIEM.', 'Monitor alerts and investigate security incidents. Build automation for incident triage and maintain operational dashboards.',()),
 ('Customer Support Technician','Practical Engineer or Technician in Electrical Engineering.', BASE,()),
 ('Electrical Practical Engineer','Certified Electrical Practical Engineer - must.',BASE,()),
 ('מהנדס חשמל','מהנדס או הנדסאי חשמל',BASE,(EE,)),
 ('Electrical Engineer','BSc in Electrical Engineering or practical engineer diploma.',BASE,(EE,)),
 ('Office Manager','',BASE,(IE,)),
 ('Operations Manager','', 'Manage office equipment, invoices and travel logistics. Coordinate employee onboarding and organize office events with colleagues.',(IE,)),
 ('Customer Service Representative','',BASE,()),
 ('Customer Support Specialist','',BASE,()),
 ('Customer Service Team Lead','',BASE,(IE,)),
 ('Customer Service Manager','',BASE,(IE,)),
 ('Business Development Manager','',BASE,()),
 ('Sales Representative','',BASE,()),
 ('Financial Analyst','', 'Prepare budgets, pricing and forecasting models to help management plan resources. Analyze monthly expenses and present results.',(IE,)),
 ('Financial Analyst','BSc in Economics only.', 'Prepare budgets, pricing and forecasting models to help management plan resources. Analyze monthly expenses and present results.',()),
 ('Software Product Manager','',BASE,(IE,)),
 ('Software Project Manager','',BASE,(IE,)),
 ('Product Manager','', 'Manage software products and the SaaS roadmap, coordinate software development teams and plan product releases with customers.',(IE,)),
 ('Procurement Manager','',BASE,()),
 ('Buyer','',BASE,()),
 ('Inventory Planner','',BASE,()),
 ('Logistics Coordinator','',BASE,()),
 ('Procurement Manager','BSc in Industrial Engineering preferred.',BASE,(IE,)),
 ('Buyer','BSc in Industrial Engineering.',BASE,(IE,)),
 ('Logistics Manager','BSc in Economics required.',BASE,()),
 ('Software Product Manager','BSc in Mechanical Engineering only.',BASE,()),
 ('מפתח/ת C++','',BASE,(CS,)),
])
def test_latest_scope_decisions(title,requirement,body,expected):
    result=classify(title,requirement,body)
    assert result.matched_tracks==expected,result.to_dict()
    if not expected:
        assert all(d.status=='outside' for d in result.decisions),result.to_dict()

@pytest.mark.parametrize('title',['Software Product Manager','Software Project Manager'])
def test_software_management_without_degree_is_red_in_iem(title):
    result=classify(title)
    assert {d.degree_color for d in result.decisions if d.status=='match'}=={'red'}


def test_technician_colleagues_do_not_exclude_engineering_jobs():
    result=classify('Hardware Engineer','BSc in Electrical Engineering.',BASE+'\nResponsibilities:\nWork with technicians and practical engineers to debug hardware.')
    assert result.matched_tracks==(EE,)


def test_preferred_iem_degree_admits_procurement_with_yellow_degree():
    result=classify('Procurement Manager','BSc in Industrial Engineering preferred.')
    assert next(d for d in result.decisions if d.track==IE).degree_color=='yellow'

@pytest.mark.parametrize('requirement,allowed',[
 ('BSc in Computer Science.', ['bachelor','master','phd']),
 ('MSc in Computer Science required.', ['master','phd']),
 ('PhD in Computer Science required.', ['phd']),
 ('MSc in Computer Science preferred.', ['bachelor','master','phd']),
 ('BSc in Computer Science required. MSc preferred.', ['bachelor','master','phd']),
 ('MSc in Computer Science or equivalent practical experience.', ['bachelor','master','phd']),
])
def test_degree_report_uses_existing_required_vs_preferred_filter(requirement,allowed):
    result=compare_job(SimpleNamespace(title='Software Engineer',description=BASE+'\nRequirements:\n'+requirement))
    assert result['education_filter']['allowed_profile_degrees']==allowed


def test_student_preference_report_uses_existing_exclusion():
    row=compare_job(SimpleNamespace(title='Software Engineer Student',description=BASE))
    assert row['search_preferences']['excluded_when_student_disabled'] is True

@pytest.mark.parametrize('requirement', ['הנדסאי/ת או מהנדס/ת חשמל - חובה', 'מהנדס/ת חשמל או הנדסאי חשמל', 'Electrical Engineer or Practical Engineer'])
def test_engineer_or_technician_alternatives_are_not_technician_only(requirement):
    result=classify('Electrical Engineer',requirement)
    assert result.matched_tracks==(EE,)
    assert next(d for d in result.decisions if d.track==EE).degree_color=='green'


def test_bsc_required_and_msc_preferred_in_flattened_feed():
    requirement='B.Sc in Electrical Engineering, Computer Science, or a related engineering field M.Sc / MBA - Advantage'
    result=classify('Product Manager',requirement)
    assert result.matched_tracks==(EE,IE)
    assert [d.degree_color for d in result.decisions]==['green','green','yellow']
    row=compare_job(SimpleNamespace(title='Product Manager',description=BASE+'\nRequirements:\n'+requirement))
    assert row['education_filter']['required_level']=='bachelor'
    assert row['education_filter']['allowed_profile_degrees']==['bachelor','master','phd']


def test_separate_preferred_degree_does_not_weaken_mandatory_other_degree():
    requirement='B.Sc. in Mechanical Engineering - Must . B.Sc. in Computer Science - Advantage.'
    assert classify('Software Engineer',requirement).matched_tracks==()


def test_software_supply_chain_security_is_not_logistics():
    result=classify('Software Security Engineer - Supply Chain','BSc in Computer Science.')
    assert result.matched_tracks==(CS,)


@pytest.mark.parametrize('requirement', ['Practical Engineer degree in Electrical Engineering.', 'הנדסאי אלקטרוניקה - חובה'])
def test_practical_engineering_degree_is_not_an_academic_degree(requirement):
    assert classify('Hardware Engineer',requirement).matched_tracks==()


def test_graduate_or_practical_engineer_is_still_accepted():
    result=classify('Technical Instructor','בוגר.ת הנדסת חשמל או הנדסאי.ת אלקטרוניקה')
    assert result.matched_tracks==(EE,)


def test_ai_security_product_management_is_software_management():
    result=classify('Product Manager, AI Security')
    assert result.matched_tracks==(IE,)
    assert all(d.degree_color=='red' for d in result.decisions)


@pytest.mark.parametrize('requirement,allowed',[
    ('M.Eng. in Electrical Engineering required.', ['master','phd']),
    ('תואר שלישי במדעי המחשב - חובה', ['phd']),
    ('דוקטורט במדעי המחשב - חובה', ['phd']),
])
def test_report_degree_hierarchy_handles_engineering_and_hebrew_levels(requirement,allowed):
    row=compare_job(SimpleNamespace(title='Research Scientist',description=BASE+'\nRequirements:\n'+requirement))
    assert row['education_filter']['allowed_profile_degrees']==allowed
