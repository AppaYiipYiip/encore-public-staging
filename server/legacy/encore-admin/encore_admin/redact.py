"""Hiding what must not be shown or sent before a program's own messages leave the machine (the owner's page, a bug report).

The messages of the stack's programs are not expected to hold a key or a password, and the services here print none; this is the net under
that expectation: anything that looks like a key, a token or a password is replaced by `***` whatever program printed it.
"""
from __future__ import annotations

import re

_QUERY = re.compile(r"([?&](?:t|s|u|token|apikey|api_key|api-key|key|password|pass|passwd|secret|authkey|auth)=)[^&\s\"']+", re.IGNORECASE)
_PAIR = re.compile(r"(?i)\b(x-api-key|x-nd-authorization|authorization|api[_-]?key|password|passwd|secret|token|authkey)(\"?\s*[:=]\s*\"?)(?:Bearer\s+)?[^\s\",;&]+")
_TAILSCALE = re.compile(r"tskey-[A-Za-z0-9-]{8,}")
_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")


def line(text: str) -> str:
    text = _QUERY.sub(r"\1***", text)
    text = _PAIR.sub(r"\1\2***", text)
    text = _BEARER.sub("Bearer ***", text)
    text = _TAILSCALE.sub("***", text)
    return _HEX.sub("***", text)
