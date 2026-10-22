"""Ids and time (docs/17 section 1): server-made ids are opaque strings with a type prefix; clients make their own for what they create,
so an offline create can be retried without duplicates."""

from __future__ import annotations

import os
import re
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U

#: `sr_` song ref, `sf_` song file, `pl_` playlist, `pe_` playlist entry, `dv_` device, `im_` import, `pn_` person, `jm_` Jam, `wk_` background work, `iv_` invitation, `rc_` password reset.
PREFIXES = frozenset({"sr", "sf", "pl", "pe", "dv", "im", "pn", "jm", "wk", "iv", "rc"})

_ID = re.compile(r"^(?P<prefix>[a-z]{2})_(?P<ulid>[0-9A-HJKMNP-TV-Z]{26})$")


def now_ms() -> int:
    return int(time.time() * 1000)


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))


def ulid(at_ms: int | None = None) -> str:
    """26 characters: 48 bits of time (so ids sort by creation) and 80 random bits."""
    stamp = now_ms() if at_ms is None else at_ms
    return _encode(stamp, 10) + _encode(int.from_bytes(os.urandom(10), "big"), 16)


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix {prefix!r}")
    return f"{prefix}_{ulid()}"


def is_id(value: object, prefix: str) -> bool:
    """Whether [value] is a well-formed id of that kind (what a client may send for something it creates)."""
    if not isinstance(value, str):
        return False
    match = _ID.match(value)
    return match is not None and match.group("prefix") == prefix
