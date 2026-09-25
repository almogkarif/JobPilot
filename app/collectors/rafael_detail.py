"""Recognize Rafael access failures without treating them as closed vacancies."""


def is_rafael_access_challenge(status_code: int, document: str) -> bool:
    """Identify the observed official-site challenge, including HTTP-200 wrappers.

    A challenge says nothing about the availability of the requested job. Callers
    must retain the existing record and mark collection incomplete.
    """
    if status_code == 247:
        return True
    lowered = document[:100_000].casefold()
    return "kramericaindustries.ac_v2.lib.js" in lowered or "window.rbzns" in lowered
