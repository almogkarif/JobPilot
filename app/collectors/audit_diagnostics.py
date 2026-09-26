"""Opt-in, task-local diagnostics for public source audits; never used for auth.

Nothing is retained during normal scans. No network/DB calls are made here.
Small sanitized DOM excerpts let an audit explain selector drift without dumping
cookies, headers, script credentials, forms or a full career page into the report.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

MAX_EVENTS = 48
MAX_DOCUMENTS = 4
MAX_EXCERPT = 6000
_STATE: ContextVar[dict | None] = ContextVar("jobpilot_public_audit", default=None)
_SECRET_KEY = re.compile(r"token|password|secret|authorization|cookie|api.?key|csrf|nonce", re.I)


def enabled() -> bool:
    return _STATE.get() is not None


def begin() -> Token:
    return _STATE.set({"events": [], "documents": [], "dropped_events": 0})


def finish(token: Token) -> dict:
    state = _STATE.get() or {}
    _STATE.reset(token)
    return state


def safe_url(value: object) -> str:
    try:
        p = urlsplit(str(value))
        if p.scheme not in {"https", "http"} or not p.hostname:
            return "[invalid URL]"
        return urlunsplit((p.scheme, p.hostname, p.path, "", ""))
    except ValueError:
        return "[invalid URL]"


def _clean(value: object, depth: int = 0):
    if depth > 5:
        return "[depth limit]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(key)[:100]: ("[redacted]" if _SECRET_KEY.search(str(key)) else _clean(item, depth + 1))
                for key, item in list(value.items())[:40]}
    if isinstance(value, (list, tuple, set)):
        return [_clean(item, depth + 1) for item in list(value)[:40]]
    text = str(value)
    text = re.sub(r"https?://[^\s\"'<>]+", lambda match: safe_url(match.group()), text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email redacted]", text)
    text = re.sub(r"(?i)\b(?:token|password|secret|authorization|cookie|api.?key|csrf|nonce)\s*[:=]\s*\S+",
                  "[credential redacted]", text)
    return text[:600]


def record(stage: str, **fields) -> None:
    state = _STATE.get()
    if state is None:
        return
    if len(state["events"]) >= MAX_EVENTS:
        state["dropped_events"] += 1
        return
    state["events"].append({"stage": stage[:100], **_clean(fields)})


def _element(node: Tag) -> dict:
    return {"tag": node.name, "id": str(node.get("id") or "")[:100],
            "class": " ".join(node.get("class") or [])[:160],
            "text": _clean(node.get_text(" ", strip=True))[:240]}


def _excerpt(node: Tag) -> str:
    """Keep selectors/structure, never form values, script code or event handlers."""
    if len(str(node)) > 150_000:
        return "[container too large for excerpt]"
    fragment = BeautifulSoup(str(node), "html.parser")
    for item in fragment.select("script, style, noscript, svg, iframe, textarea, select, option"):
        item.decompose()
    for item in fragment.find_all(True):
        original = dict(item.attrs)
        item.attrs = {key: val for key, val in original.items()
                      if key in {"class", "id", "role", "name", "type", "aria-controls", "aria-labelledby"}}
        if item.name == "input":
            # Vacancy identifiers are useful, applicant/CSRF/default values are not.
            name = str(original.get("name") or "").lower().replace("-", "_")
            value = str(original.get("value") or "")
            if name in {"job_id", "jobid", "position_id", "positionid", "vacancy_id"} and re.fullmatch(r"\d{1,12}|[A-Za-z0-9]{2}\.[A-Za-z0-9]{3}", value):
                item["value"] = value
        for key in ("href", "data-target", "data-bs-target"):
            value = str(original.get(key) or "")
            if value.startswith("#") and re.fullmatch(r"#[A-Za-z0-9_.:-]{1,100}", value):
                item[key] = value
            elif key == "href" and value.startswith(("http://", "https://")):
                item[key] = safe_url(value)
            elif key == "href" and value.startswith("/") and not value.startswith("//"):
                item[key] = value.split("?")[0].split("#")[0]
    # Do not preserve comments, including embedded settings in HTML comments.
    from bs4 import Comment
    for comment in fragment.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    text = str(fragment)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email redacted]", text)
    text = re.sub(r"(?i)\b(?:token|password|secret|authorization|cookie|api.?key|csrf|nonce)\s*[:=]\s*[^\s<>]+", "[credential redacted]", text)
    return text[:MAX_EXCERPT]


def document(url: str, html: str, *, detail: bool = False) -> None:
    """Capture bounded public structure. Diagnostic errors must not lose jobs."""
    if _STATE.get() is None:
        return
    try:
        _document(url, html, detail=detail)
    except Exception as exc:
        record("diagnostic_capture_failed", error_type=type(exc).__name__)


def _document(url: str, html: str, *, detail: bool) -> None:
    state = _STATE.get()
    if state is None or len(html.encode("utf-8")) > 4_000_000:
        return
    docs = state["documents"]
    if len(docs) >= MAX_DOCUMENTS or (not detail and any(not item["detail"] for item in docs)):
        return
    if detail and sum(bool(item["detail"]) for item in docs) >= 3:
        return
    public_url = safe_url(url)
    if any(item["url"] == public_url for item in docs):
        return
    soup = BeautifulSoup(html, "html.parser")
    embeds = [{"tag": node.name, "src": safe_url(node.get("src"))}
              for node in soup.select("script[src], iframe[src]")[:20]]
    identities = [{"tag": node.name, "url": safe_url(node.get("content") or node.get("href"))}
                  for node in soup.select('meta[property="og:url"], link[rel="canonical"]')[:5]]
    public_job_ids = []
    for node in soup.select("input[name]")[:1000]:
        name, value = str(node.get("name") or "").lower(), str(node.get("value") or "")
        if name in {"job_id", "jobid", "position_id", "positionid", "position_uid", "vacancy_id", "post_id"} and re.fullmatch(r"\d{1,12}|[A-Za-z0-9]{2}\.[A-Za-z0-9]{3}", value):
            public_job_ids.append({"name": name, "value": value})
        if len(public_job_ids) >= 40:
            break
    for node in soup.select("script, style, noscript, svg, iframe, header, nav, footer"):
        node.decompose()
    headings = [node for node in soup.select("h1,h2,h3,h4") if node.get_text(" ", strip=True)]
    entry = {"url": public_url, "detail": detail,
             "headings": [_element(node) for node in headings[:32]], "public_embeds": embeds,
             "identity_urls": identities, "public_job_ids": public_job_ids,
             "excerpts": [], "label_contexts": []}
    # Job-number labels can sit beside (not inside) the title container.
    # Preserve bounded surrounding markup, not arbitrary form values.
    for text_node in soup.find_all(string=re.compile(r"מיקום\s+משרה|מספר\s+משרה|משרה\s+מס")):
        if text_node.find_parent(["form", "textarea", "select", "option"]):
            continue
        parent = text_node.parent
        candidate = parent.parent if isinstance(parent, Tag) else None
        if isinstance(candidate, Tag) and candidate.name not in {"html", "body"} and len(str(candidate)) < 12_000:
            parent = candidate
        if isinstance(parent, Tag):
            excerpt = _excerpt(parent)[:1500]
            if excerpt not in entry["label_contexts"]:
                entry["label_contexts"].append(excerpt)
        if len(entry["label_contexts"]) >= 5:
            break
    candidates = [node for node in headings if node.name == "h1"][:2]
    candidates += [node for node in headings if re.search(
        r"דרישות|תיאור|מועמדות|job description|requirements|about the position", node.get_text(" ", strip=True), re.I)][:2]
    if not candidates:
        candidates = headings[:2]
    for node in candidates[:3]:
        parent = node
        for _ in range(3):
            candidate = parent.parent
            if not isinstance(candidate, Tag) or candidate.name in {"html", "body"}:
                break
            if len(str(candidate)) > 30_000:
                break
            parent = candidate
        excerpt = _excerpt(parent)
        if excerpt not in entry["excerpts"]:
            entry["excerpts"].append(excerpt)
    links = []
    for anchor in soup.select("a[href]")[:120]:
        href = str(anchor["href"])
        if href.startswith(("https://", "http://")):
            href = safe_url(href)
        elif href.startswith(("/", "#")) and not href.startswith("//"):
            href = _clean(href.split("?")[0])[:180]
        else:
            continue
        links.append({"text": _clean(anchor.get_text(" ", strip=True))[:100], "href": href})
    entry["links"] = links[:60]
    # Public selector identities only; never applicant values or hidden CSRF.
    entry["role_ids"] = [{"tag": n.name, "id": str(n.get("id") or "")[:100]}
                         for n in soup.select("[id]") if re.search(r"job|position|vacancy|accordion|collapse|popup", str(n.get("id")), re.I)][:50]
    docs.append(entry)
