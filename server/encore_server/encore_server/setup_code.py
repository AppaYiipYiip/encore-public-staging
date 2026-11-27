"""The setup code (docs/36 section 2, hidden risk H36): what proves, to a server that has no owner yet, that the person at the browser is the person who installed it.

Whoever reaches a server before its owner exists could otherwise become the owner. So the installer makes a short code (`7KQ-4MZ`), writes it into the install's `.env` (root only,
mode 600) and shows it once on the computer's own screen; the first-run pages work only with it, and only while no person exists. This module is the code itself: its alphabet, how a
typed one is read, and the one comparison. It holds no state and never logs a code.

Six characters of 31 (no 0 O 1 I L, which are mistaken for each other) are about 30 bits: enough because a wrong try costs a wait (five a minute from one address, thirty in all), the
pages answer only on the home network, and the code lives only until the owner is made.
"""

from __future__ import annotations

import hmac
import secrets

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
LENGTH = 6


def normalize(text: object) -> str:
    """What was typed or read, as the bare code: capitals, with the spaces and dashes a person (or a line wrap) adds taken out. Not a string: nothing."""
    if not isinstance(text, str):
        return ""
    return "".join(ch for ch in text.strip().upper() if ch not in " -\t\r\n")


def well_formed(text: object) -> bool:
    bare = normalize(text)
    return len(bare) == LENGTH and all(ch in ALPHABET for ch in bare)


def show(text: str) -> str:
    """`7KQ4MZ` as it is shown and written: `7KQ-4MZ`."""
    bare = normalize(text)
    return f"{bare[:3]}-{bare[3:]}"


def new_code() -> str:
    """A fresh code, in the form it is shown in. The installer makes its own in shell (`deploy/install.sh`); this is for tests and for a server that has to make one."""
    return show("".join(secrets.choice(ALPHABET) for _ in range(LENGTH)))


def matches(configured: str, given: object) -> bool:
    """Is [given] the configured code? Constant time, and false for a configured code that is not well formed (a hand-edited weak one never opens the pages)."""
    if not well_formed(configured):
        return False
    return hmac.compare_digest(normalize(configured).encode(), normalize(given).encode())
