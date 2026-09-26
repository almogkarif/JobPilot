"""Bezeq's public Adam vacancy feed, linked by its careers page."""
from datetime import datetime, timezone
import json
import re

from .base import JobCollection, NormalizedJob, PreserveExistingJobs
from .expansion_ats import bounded_public_get
from ..services.job_text import clean_job_text, job_text_quality
from ..services.source_quality import is_navigation_title

FEED = 'https://d-api.bezeq.co.il/api/Adam/GetActiveJobs'
APPLY = 'https://www.bezeq.co.il/career/jobs/form/'
MAX_JOBS = 200
AREAS = {'גוש דן', 'השפלה', 'חיפה והקריות', 'ירושלים יו"ש', 'דרום', 'צפון', 'מרכז', 'כל הארץ'}


def _date(value):
    value = str(value or '').strip()
    if not value or value.startswith('1900-01-01') or value == '01/01/1900':
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%d/%m/%Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError('Unrecognized vacancy date')


def parse_bezeq(document, company='Bezeq', *, today=None):
    payload = json.loads(document)
    if (not isinstance(payload, dict) or payload.get('isSuccessfull') is not True
            or payload.get('error') or not isinstance(payload.get('data'), list)
            or len(payload['data']) > MAX_JOBS):
        raise PreserveExistingJobs('Bezeq returned an invalid or oversized vacancy feed')
    today = today or datetime.now(timezone.utc).date()
    jobs, seen = [], set()
    for row in payload['data']:
        if not isinstance(row, dict):
            raise PreserveExistingJobs('Bezeq returned an invalid vacancy row')
        uid = str(row.get('order_id') or '')
        if not re.fullmatch(r'\d{1,10}', uid) or uid in seen:
            raise PreserveExistingJobs('Bezeq returned missing or repeated vacancy IDs')
        seen.add(uid)
        try:
            closed, deadline = _date(row.get('close_date')), _date(row.get('deadline_date'))
        except ValueError:
            continue
        # The active endpoint currently includes rows with past close/deadline
        # fields. Their availability is ambiguous; retain a partial snapshot.
        if closed is not None and closed <= today or deadline is not None and deadline < today:
            continue
        title = str(row.get('description') or '').strip()
        text = clean_job_text(row.get('notes') or row.get('notes_text') or '')
        area = str(row.get('work_area') or '').strip()
        if (not title or len(title) > 300 or is_navigation_title(title)
                or area not in AREAS or not 0 < len(text) <= 24000
                or job_text_quality(text) != 'complete'):
            continue
        # Work area is a per-vacancy employment field. living_area* describes
        # candidate residence filters and must not establish the work location.
        location = str(row.get('Order_place') or '').strip() or area
        if len(location) > 200:
            continue
        url = f'{APPLY}?jobs={uid}'
        jobs.append(NormalizedJob(uid, title, company, location + ', Israel',
                                  'unknown', text, url, url))
    return JobCollection(jobs, complete=False)


async def collect_bezeq(company='Bezeq'):
    return parse_bezeq(await bounded_public_get(FEED), company)
