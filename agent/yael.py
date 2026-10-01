"""Yael's verified Adam job form: normal browser submission, one guarded POST."""
from __future__ import annotations

import hashlib
import json
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlparse

from app.services.application_submission import yael_job_id
from app.utils import split_name


SUBMISSION_URL = 'https://yaelgroup.com/wp-admin/admin-ajax.php'
THANK_YOU_URL = 'https://yaelgroup.com/job-thank-you/'
MAX_CV_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 8192
FORM_FIELDS = {
    'form_func', 'job_id', 'job_name', 'link_page_success', 'first_name', 'last_name',
    'mobile', 'upload_cv', 'linkedin_profile', 'middle_name', 'job_source',
    'job_source_details', 'privacy_policy', 'submit',
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def response_outcome(status: int, body: str) -> str:
    text = str(body or '')
    if status in {403, 429} or any(term in text.casefold() for term in (
        'captcha', 'forbidden', 'access denied', 'אימות אנושי', 'too many requests',
    )):
        return 'blocked'
    if status >= 500:
        return 'unknown'
    if status >= 400:
        return 'rejected'
    if not 200 <= status < 300 or len(text.encode('utf-8')) > MAX_RESPONSE_BYTES:
        return 'unknown'
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except (ValueError, TypeError):
        return 'unknown'
    if not isinstance(payload, dict):
        return 'unknown'
    if (payload.get('status') == 'error' or payload.get('error') or payload.get('errors')
            or any(value is False or value == 0
                   or isinstance(value, str) and value.strip().casefold() == 'false'
                   for value in (payload.get('success'), payload.get('submitted')))):
        return 'rejected'
    message = ' '.join(str(payload.get('msg') or '').split())
    # Observed on the single authorized job-specific POST, October 1, 2026.
    return 'accepted' if payload.get('status') == 'success' and message == (
        'תודה על פנייתכם! ניצור אתכם קשר בהקדם.'
    ) else 'unknown'


def submission_fields(request) -> dict:
    """Validate bounded multipart parts, retaining a hash instead of CV bytes."""
    content_type = request.headers.get('content-type', '')
    body = request.post_data_buffer or b''
    if (request.method != 'POST' or request.url != SUBMISSION_URL or len(content_type) > 256
            or not content_type.lower().startswith('multipart/form-data;')
            or not 0 < len(body) <= MAX_CV_BYTES + 64 * 1024):
        return {}
    try:
        message = BytesParser(policy=policy.default).parsebytes(
            b'Content-Type: ' + content_type.encode('ascii') + b'\r\n\r\n' + body)
        if not message.is_multipart() or message.defects:
            return {}
        fields, cv = {}, None
        for part in message.iter_parts():
            name = part.get_param('name', header='content-disposition')
            if (name not in FORM_FIELDS | {'action', 'related_products', 'recaptcha_token'}
                    or part.is_multipart() or part.defects or part.get('Content-Transfer-Encoding')
                    or part.get_content_disposition() != 'form-data'):
                return {}
            value = part.get_payload(decode=True) or b''
            if name == 'upload_cv':
                if cv is not None or not part.get_filename() or not 0 < len(value) <= MAX_CV_BYTES:
                    return {}
                cv = {'cv_filename': part.get_filename(), 'cv_sha256': hashlib.sha256(value).hexdigest()}
            else:
                if part.get_filename() is not None or len(value) > (16384 if name == 'recaptcha_token' else 2048):
                    return {}
                fields.setdefault(name, []).append(value.decode('utf-8'))
        token = fields.pop('recaptcha_token', [])
        if cv is None or len(token) != 1 or not token[0].strip():
            return {}
        return {'fields': fields, **cv}
    except (ValueError, TypeError, UnicodeError):
        return {}


def fill_yael_application(page, task: dict, auto_submit: bool, progress=None) -> dict:
    from .browser import ApplicationBlocked, _detect_captcha

    job_id = yael_job_id(task['job']['apply_url'])
    sent, responses, denied = [], [], []
    armed = False

    def blocked(kind, message, *, outcome='unknown', **kwargs):
        return ApplicationBlocked(kind, 'הגשה לקבוצת יעל', message, message, page.url,
                                  diagnostics={'employer_job_id': job_id, 'request_sent': bool(sent),
                                               'yael_response_outcome': outcome,
                                               'http_status': responses[-1][0] if responses else None}, **kwargs)

    form = page.locator('form#job_form')
    if not job_id or yael_job_id(page.url) != job_id or form.count() != 1:
        raise blocked('application_form_missing', 'לא נמצא טופס יחיד המשויך למשרת יעל המבוקשת.')
    for name, value in (('job_id', job_id), ('form_func', 'adam_send_job_mail'),
                        ('link_page_success', THANK_YOU_URL)):
        field = form.locator(f'input[type="hidden"][name="{name}"]')
        if field.count() != 1 or field.input_value() != value:
            raise blocked('application_form_missing', 'מזהי הטופס אינם תואמים למשרה המבוקשת.')
    title = form.locator('input[type="hidden"][name="job_name"]')
    if (title.count() != 1 or not title.input_value().strip() or page.locator('h1').count() != 1
            or ' '.join(page.locator('h1').inner_text().split()) != ' '.join(title.input_value().split())):
        raise blocked('application_form_missing', 'כותרת המשרה אינה תואמת לטופס ההגשה.')
    if set(form.locator('input,select,textarea,button').evaluate_all('els=>els.map(e=>e.name)')) - FORM_FIELDS:
        raise blocked('choice_required', 'נוספו שדות בטופס יעל; יש לבדוק אותם לפני שליחה.')
    profile = task['profile']
    first, last = split_name(str(profile.get('full_name') or ''))
    phone = re.sub(r'\D', '', str(profile.get('phone') or ''))
    phone = re.sub(r'^(?:00972|972)', '0', phone)
    if not first or not last or not re.fullmatch(r'05\d{8}', phone):
        raise blocked('profile_missing', 'נדרשים שם מלא ומספר נייד ישראלי תקין להגשה.')
    controls = {'first_name': first, 'last_name': last, 'mobile': phone}
    cv = Path(str(profile.get('cv_path') or ''))
    try:
        if cv.suffix.casefold() not in {'.pdf', '.doc', '.docx'} or not 0 < cv.stat().st_size <= MAX_CV_BYTES:
            raise ValueError('Invalid CV')
        with cv.open('rb') as stream:
            cv_bytes = stream.read(MAX_CV_BYTES + 1)
        if not 0 < len(cv_bytes) <= MAX_CV_BYTES:
            raise ValueError('Invalid CV')
    except (OSError, ValueError):
        raise blocked('file_required', 'נדרש קובץ קורות חיים PDF, DOC או DOCX בגודל עד 10MB.')
    expected = {'cv_filename': cv.name, 'cv_sha256': hashlib.sha256(cv_bytes).hexdigest()}

    def guard(route):
        request = route.request
        host = (urlparse(request.url).hostname or '').casefold()
        if request.method in {'GET', 'HEAD', 'OPTIONS'} or not (host == 'yaelgroup.com' or host.endswith('.yaelgroup.com')):
            return route.fallback()
        fields = submission_fields(request) if armed and not sent and not denied else {}
        if fields != expected:
            denied.append(True)
            return route.abort()
        sent.append(request)
        route.fallback()
        if progress:
            progress('submit_request_sent', 'בקשת המועמדות נשלחה למשרת יעל', page.url)

    def capture(response):
        if response.request not in sent or response.url != SUBMISSION_URL:
            return
        try:
            length = response.headers.get('content-length', '')
            body = response.text() if not length.isdigit() or int(length) <= MAX_RESPONSE_BYTES else ''
            responses.append((response.status, body if len(body.encode('utf-8')) <= MAX_RESPONSE_BYTES else ''))
        except Exception:
            responses.append((response.status, ''))

    def observe(source, payload):
        if (sent and source.get('page') == page and source.get('frame') == page.main_frame
                and isinstance(payload, dict) and payload.get('url') == SUBMISSION_URL
                and type(payload.get('status')) is int and isinstance(payload.get('body'), str)):
            body = payload['body']
            responses.append((payload['status'], body if len(body.encode('utf-8')) <= MAX_RESPONSE_BYTES else ''))

    page.route('**/*', guard)
    page.on('response', capture)
    try:
        # Preserve the ordinary XHR receipt before the site's success handler
        # navigates away. This observer does not replace or replay the request.
        binding = f'__jobpilot_yael_receipt_{id(sent)}'
        page.expose_binding(binding, observe)
        page.evaluate('''({url,limit,binding})=>{
          const original=XMLHttpRequest.prototype.open;
          XMLHttpRequest.prototype.open=function(method,target,...args){
            if(String(method).toUpperCase()==='POST'&&new URL(target,location.href).href===url){
              this.addEventListener('load',()=>{
                try{const body=this.responseText;
                  window[binding]({url:this.responseURL,status:this.status,body:body.length<=limit?body:''}).catch(()=>{});
                }catch(_){}
              });
            }
            return original.call(this,method,target,...args);
          };
        }''', {'url': SUBMISSION_URL, 'limit': MAX_RESPONSE_BYTES, 'binding': binding})
        reject_cookies = page.get_by_role('button', name='דחה הכל', exact=True)
        if reject_cookies.count() == 1 and reject_cookies.is_visible():
            reject_cookies.click()
        for name, value in controls.items():
            control = form.locator(f'input[name="{name}"]')
            if control.count() != 1:
                raise blocked('profile_missing', 'חסר שדה פרטי קשר נדרש בטופס.')
            control.fill(value)
        upload = form.locator('input[type="file"][name="upload_cv"]')
        if upload.count() != 1:
            raise blocked('file_required', 'לא נמצא שדה קורות חיים יחיד בטופס.')
        upload.set_input_files({'name': cv.name, 'buffer': cv_bytes, 'mimeType': {
            '.pdf': 'application/pdf', '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        }[cv.suffix.casefold()]})
        del cv_bytes
        source = form.locator('select[name="job_source"]')
        if source.count() != 1:
            raise blocked('choice_required', 'לא נמצא שדה מקור מועמדות מוכר.')
        if source.is_visible():
            source.select_option(label='חיפוש יזום שלי')
        else:
            source.locator('..').locator('.select-styled').click()
            source.locator('..').get_by_text('חיפוש יזום שלי', exact=True).last.click()
        consent = form.locator('input[type="checkbox"][name="privacy_policy"]')
        if (consent.count() != 1 or ' '.join(consent.locator('..').inner_text().split()) != 'אני מסכים למדיניות הפרטיות'):
            raise blocked('choice_required', 'תנאי ההסכמה השתנו; נדרשת בדיקה לפני שליחה.')
        consent.check()
        fields = form.evaluate('''f=>{const out={};for(const [k,v] of new FormData(f)){
          if(!(v instanceof File))(out[k]??=[]).push(v);
        }return out}''')
        if (any(fields.get(k) != [v] for k, v in controls.items())
                or fields.get('job_source') != ['חיפוש יזום שלי']
                or fields.get('privacy_policy') != ['on']
                or any(fields.get(k) != [v] for k, v in (
                    ('job_id', job_id), ('form_func', 'adam_send_job_mail'), ('link_page_success', THANK_YOU_URL)))
                or any(fields.get('middle_name', []))):
            raise blocked('submit_not_sent', 'פרטי הטופס אינם תואמים לפרופיל ולמשרה.')
        expected['fields'] = {**fields, 'action': ['send_site_forms'], 'related_products': ['[]']}
        if not form.evaluate('f=>Boolean(window.jQuery && typeof jQuery(f).valid==="function" && jQuery(f).valid())'):
            raise blocked('submit_not_sent', 'הטופס לא עבר את בדיקת התקינות של האתר.')
        _detect_captcha(page)
        if progress:
            progress('details_filled', 'פרטי הקשר וקורות החיים מולאו בטופס יעל', page.url)
        if not auto_submit:
            raise blocked('review_before_submit', 'הטופס מולא ונשאר פתוח לפני השליחה הסופית.', options=['אשר ושלח', 'דלג'])
        if denied or yael_job_id(page.url) != job_id:
            raise blocked('submit_not_sent', 'הטופס השתנה; לא נשלחה מועמדות.')
        submit = form.get_by_role('button', name='שלח', exact=True)
        if submit.count() != 1:
            raise blocked('submit_button_missing', 'לא נמצא כפתור שליחה יחיד בטופס.')
        armed = True
        try:
            submit.click()
        except Exception:
            if not sent and not denied:
                raise
        for _ in range(60):
            if responses:
                outcomes = [response_outcome(status, body) for status, body in responses]
                bad = next((x for x in ('blocked', 'rejected') if x in outcomes), None)
                if bad:
                    raise blocked('anti_automation_blocked' if bad == 'blocked' else 'submit_rejected',
                                  'יעל חסמה או דחתה את ההגשה; לא תבוצע שליחה חוזרת אוטומטית.', outcome=bad)
                if 'accepted' in outcomes:
                    evidence = f'Yael accepted application for job {job_id} (job form response: success)'
                    return {'submitted': True, 'message': evidence, 'page_url': page.url,
                            'confirmation_text': evidence, 'external_application_id': '',
                            'evidence': [{'type': 'ats_submission_response', 'value': evidence, 'url': SUBMISSION_URL}]}
                if any(body.strip() or not 200 <= status < 300 for status, body in responses):
                    break
            if denied and not sent:
                break
            try:
                _detect_captcha(page)
            except ApplicationBlocked as exc:
                raise blocked('confirmation_missing' if sent else exc.kind,
                              'נדרש אימות אנושי; יש לבדוק קבלה לפני ניסיון נוסף.' if sent
                              else 'נדרש אימות אנושי לפני השליחה.', outcome='blocked') from exc
            page.wait_for_timeout(500)
        raise blocked('confirmation_missing' if sent else 'submit_not_sent',
                      'לא התקבל אישור קבלה מפורש מיעל. יש לבדוק לפני ניסיון נוסף.' if sent
                      else 'לא נשלחה בקשת מועמדות תקינה למשרה.')
    except ApplicationBlocked:
        raise
    except Exception as exc:
        if sent:
            raise blocked('confirmation_missing', 'החיבור נקטע אחרי השליחה; יש לבדוק קבלה לפני כל ניסיון נוסף.') from exc
        raise
    finally:
        armed = False
        page.remove_listener('response', capture)
