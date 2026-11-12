"""Small, explicit security helpers.

Sessions: TalentSignal has no user accounts yet. The browser generates a
random session id (UUID4) once and sends it as ``X-Session-Id``; every run,
shortlist and uploaded dataset is stored with that owner and only returned to
the same session. This separates history between people sharing a hosted
instance, but it is NOT authentication: anyone who obtains the id can act as
that session. Put the app behind real authentication before exposing it to
untrusted users (documented in the README).
"""
from __future__ import annotations

import re
import unicodedata

from fastapi import Header

from app.core.errors import AppError

SESSION_RE = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$")
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def session_owner(x_session_id: str | None = Header(default=None)) -> str:
    if not x_session_id or not SESSION_RE.match(x_session_id.lower()):
        raise AppError(400, "invalid_session", "A valid X-Session-Id header (UUID) is required.")
    return x_session_id.lower().replace("-", "")


def safe_display_name(filename: str, max_len: int = 120) -> str:
    """Display-only name: strips paths, control and unusual characters."""
    name = unicodedata.normalize("NFKC", filename or "").replace("\\", "/").split("/")[-1]
    name = SAFE_NAME_RE.sub("_", name).strip(" .")
    return (name or "dataset")[:max_len]


def csv_safe(value):
    """Neutralise spreadsheet formula injection in exported text cells."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value
