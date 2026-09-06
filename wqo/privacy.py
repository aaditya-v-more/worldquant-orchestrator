"""Keep authentication material out of public CLI output and diagnostics."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_SENSITIVE = re.compile(r"password|passwd|secret|token|cookie|session|authorization|api[-_]?key|credential", re.I)
_PAIR = re.compile(r'''(?i)((?:[\w-]*(?:password|passwd|secret|token|cookie|session|authorization|api[_-]?key)[\w-]*)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''')
_BEARER = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/=._-]+")


def redact(value):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if _SENSITIVE.search(str(key)) else redact(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _BEARER.sub(r"\1 [REDACTED]", _PAIR.sub(r"\1[REDACTED]", value))
    return value


def diagnostic_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))


def response_detail(response) -> str:
    # Arbitrary server text can echo secrets with no recognizable field name.
    # Preserve status diagnostics; structured API payloads remain available via
    # the explicitly invoked raw read command, with field redaction.
    return "response body omitted from diagnostic output"
