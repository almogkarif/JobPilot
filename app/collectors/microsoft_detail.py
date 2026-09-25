"""Read Microsoft's public position response without mixing recommended jobs."""
from ..services.job_text import clean_job_text, job_text_quality


def microsoft_position_detail(payload, external_id):
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict) or str(data.get('id')) != str(external_id):
        return None
    title = str(data.get('name') or '').strip()
    description = clean_job_text(data.get('jobDescription') or '')
    if not title or len(title) > 500 or len(description) > 24000 or job_text_quality(description) != 'complete':
        return None
    # A fallback response may still carry the complete text of an expired job.
    # It proves content, not that applications remain open.
    fallback = bool((payload.get('metadata') or {}).get('isFallback'))
    return dict(title=title, text=description, location=str(data.get('location') or '')[:500],
                _verified_job=True, _detail_complete=True,
                _availability_unverified=fallback)
