"""Extract explicit employment entries without guessing ambiguous employer/title order."""
import re

_MONTHS = {name: index for index, names in enumerate([
    ('jan', 'january'), ('feb', 'february'), ('mar', 'march'), ('apr', 'april'),
    ('may',), ('jun', 'june'), ('jul', 'july'), ('aug', 'august'),
    ('sep', 'sept', 'september'), ('oct', 'october'), ('nov', 'november'), ('dec', 'december'),
], 1) for name in names}
_DATE = r'(?:[A-Za-z]+\.?\s+(?:19|20)\d{2}|(?:0?[1-9]|1[0-2])/(?:19|20)\d{2}|(?:19|20)\d{2}(?:-(?:0[1-9]|1[0-2]))?)'
_RANGE = re.compile(r'(?<!\w)(' + _DATE + r')\s*(?:[-–—]|\bto\b|עד)\s*(' + _DATE + r'|present|current|now|היום|כיום)(?!\w)', re.I)
_START = re.compile(r'(?:work(?:ing)? experience|professional experience|professional background|career history|employment(?: history| experience)?|work history|experience|ניסיון תעסוקתי|ניסיון מקצועי|נסיון תעסוקתי|נסיון מקצועי)\s*:?$', re.I)
_STOP = re.compile(r'(?:education|academic background|skills|technical skills|projects|languages|certifications|references|volunteering|military service|השכלה(?: אקדמית)?|שפות|כישורים|פרויקטים|שירות צבאי)\s*:?$', re.I)
_LABELS = {'job title': 'job_title', 'title': 'job_title', 'role': 'job_title', 'תפקיד': 'job_title',
           'company': 'company', 'employer': 'company', 'חברה': 'company', 'מעסיק': 'company',
           'location': 'location', 'מיקום': 'location'}
_ROLE = re.compile(r'\b(?:engineer|developer|analyst|manager|director|designer|accountant|recruiter|specialist|technician|intern|consultant|coordinator|assistant|scientist|researcher|research student|administrator|qa|lead)\b|מהנדס|מפתח|מנהל|אנליסט|רכז|בודק|חוקר', re.I)


def _date(value: str) -> str:
    value = value.strip().lower()
    if value in {'present', 'current', 'now', 'היום', 'כיום'}:
        return ''
    match = re.fullmatch(r'([a-z]+)\.?\s+(\d{4})', value)
    if match:
        month = _MONTHS.get(match[1])
        return f'{match[2]}-{month:02d}' if month else ''
    match = re.fullmatch(r'(\d{1,2})/(\d{4})', value)
    return f'{match[2]}-{int(match[1]):02d}' if match else value


def _header(line: str) -> dict[str, str]:
    labelled = re.fullmatch(r'([^:]+):\s*(.+)', line)
    if labelled and labelled[1].casefold() in _LABELS:
        return {_LABELS[labelled[1].casefold()]: labelled[2].strip()}
    parts = re.split(r'\s+(?:at|@)\s+', line, maxsplit=1, flags=re.I)
    if len(parts) == 2 and _ROLE.search(parts[0]) and len(line) < 160:
        return {'job_title': parts[0], 'company': parts[1]}
    # Employer, Title — Specialty is a common header layout. The dash
    # belongs to the title; split the comma before considering dash delimiters.
    comma_parts = line.split(',', 1)
    if len(comma_parts) == 2 and len(line) < 200:
        left, right = [part.strip() for part in comma_parts]
        if left and right and bool(_ROLE.search(left)) != bool(_ROLE.search(right)):
            return {'job_title': left if _ROLE.search(left) else right,
                    'company': right if _ROLE.search(left) else left}
    parts = re.split(r'\s*[|]\s*|\s+[-–—]\s+', line)
    if len(parts) >= 2:
        roles = [index for index, part in enumerate(parts[:2]) if _ROLE.search(part)]
        if len(roles) == 1:
            index = roles[0]
            result = {'job_title': parts[index], 'company': parts[1-index]}
            if len(parts) == 3:
                result['location'] = parts[2]
            return result
    return {}


def detect_resume_employment(text: str) -> list[dict[str, str]]:
    entries = []
    current = {}
    description = []
    active = False

    def finish():
        nonlocal current, description
        if current.get('job_title') and current.get('company'):
            if description:
                current['description'] = '\n'.join(description)[:2000]
            if current not in entries:
                entries.append(current)
        current, description = {}, []

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if _START.fullmatch(line):
            finish(); active = True
            continue
        if _STOP.fullmatch(line):
            finish(); active = False
            continue
        if not active or not line:
            continue
        # Accept stacked role/employer headers only next to explicit dates.
        if index < len(lines) and (
                (index + 1 < len(lines) and _RANGE.fullmatch(lines[index + 1].strip()))
                or ('start_date' in current and not current.get('job_title') and not current.get('company'))):
            next_line = lines[index].strip()
            if (line and next_line and len(line) < 120 and len(next_line) < 120
                    and not re.match(r'^[•*\-]', line)
                    and not re.match(r'^[•*\-]', next_line)
                    and not _header(line) and not _header(next_line)
                    and not _START.fullmatch(next_line) and not _STOP.fullmatch(next_line)
                    and bool(_ROLE.search(line)) != bool(_ROLE.search(next_line))):
                line = line + ' | ' + next_line
                index += 1
        dates = None if re.match(r'^[•*\-]\s', line) else _RANGE.search(line)
        remaining = (_RANGE.sub('', line) if dates else line).strip(' ,|–—-')
        employment_type = re.search(r'\((full[- ]time|part[- ]time|contract|internship|self[- ]employed)\)', remaining, re.I)
        header_text = (remaining[:employment_type.start()] + remaining[employment_type.end():]).strip() if employment_type else remaining
        header = {} if re.match(r'^[•*\-]\s', line) else _header(header_text)
        # A second identified role starts a new entry; date-only lines attach to
        # the header above, while a new date range starts the following entry.
        if ((header.get('job_title') and current.get('job_title'))
                or (header.get('company') and current.get('company'))
                or (dates and 'start_date' in current)):
            finish()
        if dates:
            start = _date(dates[1])
            end = _date(dates[2])
            if start and (not end or start <= end):
                current.update(start_date=start, end_date=end)
        if header:
            current.update(header)
            if employment_type:
                current['employment_type'] = employment_type[1].lower().replace(' ', '-').capitalize()
        elif remaining:
            if remaining.casefold() in {'full-time', 'part-time', 'contract', 'internship', 'self-employed'}:
                current['employment_type'] = remaining.capitalize()
            else:
                description.append(remaining)
    finish()
    # Undated entries stay after dated entries. A blank end date alone does not
    # prove current employment, so ordering uses the explicit starting date.
    return sorted(entries, key=lambda entry: entry.get('start_date', ''), reverse=True)
