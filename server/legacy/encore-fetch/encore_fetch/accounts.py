"""The YouTube accounts the server may use (docs/50).

A signed-in YouTube account has its own, much larger allowance than a visitor (about 2,000 songs an hour against about 300:
yt-dlp wiki), and may fetch age-restricted songs. The person signs in once in a browser window shown by the admin website
(never by handing over a cookie), the server keeps that session as one private file per account, and every yt-dlp run asks
[Accounts.lease] which account's cookies to use:

* the work is **split**: each run takes the account with the most room left this hour (the one used longest ago on a tie);
* each account has its own **pace** (gentle 400, normal 800, fast 1,500 songs an hour; gentle until the owner says
  otherwise) and its own **rest** after YouTube refuses it (90 s, doubling to 30 min), while the others carry on;
* an account refused three times running, or whose login has run out, **asks for a new sign-in** and is not used;
* with no usable account a run goes out with no cookies: the visitor's allowance, as before.

What each account did is kept (a small log, two days) and shown on its card, so one account can be judged before a second
is added. The files and the list live in one folder; a login is never shown back, never logged, mode 600.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import cookies as login
from .cookies import CookieProblem, Lease

log = logging.getLogger("encore_fetch.accounts")

#: Songs an hour an account is driven at, by the pace the owner chose. The default is the gentle one: the harder an
#: account is driven, the likelier it is to be banned.
PACES = {"gentle": 400, "normal": 800, "fast": 1500}
DEFAULT_PACE = "gentle"
REST_BASE_S = 90.0
REST_MAX_S = 1800.0
#: Refusals in a row, with no good answer between, after which an account asks for a new sign-in.
ATTENTION_AFTER = 3
KEEP_S = 2 * 86400.0
LABEL_MAX = 40


@dataclass
class Account:
    id: str
    label: str
    added: float
    pace: str = DEFAULT_PACE
    cap: int = 0
    rest_until: float = 0.0
    blocks: int = 0
    last_refusal: float = 0.0
    last_shrink: float = 0.0
    attention: bool = False
    #: Whose sign-in it is, as Google says (identity.py); empty when it could not be asked.
    email: str = ""
    name: str = ""


_GENERIC_LABEL = re.compile(r"YouTube account( \d+)?")


class Accounts:
    def __init__(self, directory: Path, *, legacy_file: Path | None = None,
                 clock: Callable[[], float] = time.time,
                 identify: Callable[[Path], dict | None] | None = None,
                 identify_in_background: bool = False) -> None:
        self._dir = directory
        self._clock = clock
        self._identify = identify
        self._lock = threading.RLock()
        self._accounts: dict[str, Account] = {}
        #: (time, account id, "use" | "blocked"), the last two days
        self._events: deque[tuple[float, str, str]] = deque()
        self._last_use: dict[str, float] = {}
        self._legacy = legacy_file
        self._legacy_seen: tuple[float, int] | None = None
        self._load()
        self._adopt_waiting()
        if identify is not None and identify_in_background:
            # Accounts saved before the name was asked for: ask now, without holding up the start.
            threading.Thread(target=self.identify_missing, daemon=True, name="account-names").start()

    # ------------------------------------------------------------------ files

    def _list_path(self) -> Path:
        return self._dir / "accounts.json"

    def _usage_path(self) -> Path:
        return self._dir / "usage.jsonl"

    def _file(self, account_id: str) -> Path:
        return self._dir / f"{account_id}.txt"

    def _load(self) -> None:
        try:
            data = json.loads(self._list_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = []
        for item in data if isinstance(data, list) else []:
            try:
                pace = item.get("pace") if item.get("pace") in PACES else DEFAULT_PACE
                account = Account(
                    id=str(item["id"]), label=str(item["label"])[:LABEL_MAX], added=float(item["added"]), pace=pace,
                    cap=int(item.get("cap", PACES[pace])), rest_until=float(item.get("restUntil", 0.0)),
                    blocks=int(item.get("blocks", 0)), last_refusal=float(item.get("lastRefusal", 0.0)),
                    last_shrink=float(item.get("lastShrink", 0.0)), attention=bool(item.get("attention", False)),
                    email=str(item.get("email", ""))[:120], name=str(item.get("name", ""))[:60])
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if not 1 <= account.cap <= PACES[account.pace]:
                account.cap = PACES[account.pace]
            self._accounts[account.id] = account
        horizon = self._clock() - KEEP_S
        try:
            lines = self._usage_path().read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        kept = []
        for line in lines:
            try:
                event = json.loads(line)
                stamp, who, what = float(event["t"]), str(event["a"]), str(event["o"])
            except (KeyError, TypeError, ValueError):
                continue
            if stamp >= horizon:
                self._events.append((stamp, who, what))
                kept.append(line)
        if len(kept) != len(lines):
            self._write_text(self._usage_path(), "".join(f"{line}\n" for line in kept))

    def _write_text(self, path: Path, text: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(tmp, path)
        except OSError:
            log.warning("could not write %s", path.name)

    def _save(self) -> None:
        self._write_text(self._list_path(), json.dumps([
            {"id": a.id, "label": a.label, "added": a.added, "pace": a.pace, "cap": a.cap, "restUntil": a.rest_until,
             "blocks": a.blocks, "lastRefusal": a.last_refusal, "lastShrink": a.last_shrink, "attention": a.attention,
             "email": a.email, "name": a.name}
            for a in self._accounts.values()], separators=(",", ":")))

    def _record(self, account_id: str, what: str) -> None:
        now = self._clock()
        self._events.append((now, account_id, what))
        horizon = now - KEEP_S
        while self._events and self._events[0][0] < horizon:
            self._events.popleft()
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._usage_path(), "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"t": now, "a": account_id, "o": what}, separators=(",", ":")) + "\n")
        except OSError:
            log.warning("the usage log could not be written")

    def _adopt_waiting(self) -> None:
        """A login file dropped in the old single-file place (the first version, or `s10_youtube_login.sh`) becomes an account,
        also while the service runs. A file that cannot be used is looked at again only when it changes."""
        legacy = self._legacy
        if legacy is None:
            return
        try:
            info = legacy.stat()
        except OSError:
            return
        mark = (info.st_mtime, info.st_size)
        if info.st_size == 0 or mark == self._legacy_seen:
            return
        with self._lock:
            self._legacy_seen = mark
            self._adopt(legacy)

    def _adopt(self, legacy: Path) -> None:
        """A server that had one login file (the first version) keeps it as an account."""
        try:
            text = legacy.read_text(encoding="utf-8", errors="replace")
            login.check_text(text, now=self._clock())
        except (OSError, CookieProblem):
            return
        account = self._make("YouTube account", text)
        try:
            legacy.unlink()
        except OSError:
            pass
        log.info("the single YouTube login became the account %s", account.id)

    def _make(self, label: str, text: str) -> Account:
        account_id = secrets.token_hex(4)
        login.install(str(self._file(account_id)), text, now=self._clock())
        account = Account(id=account_id, label=self._clean(label), added=self._clock(), cap=PACES[DEFAULT_PACE])
        self._who(account)
        if _GENERIC_LABEL.fullmatch(account.label) and (account.email or account.name):
            account.label = (account.email or account.name)[:LABEL_MAX]
        self._accounts[account_id] = account
        self._save()
        return account

    def _who(self, account: Account) -> bool:
        """Asks (once) whose sign-in this is; never fails: an account without a known name is still an account."""
        if self._identify is None:
            return False
        try:
            found = self._identify(self._file(account.id))
        except Exception:  # noqa: BLE001 - see above
            return False
        if not isinstance(found, dict) or not found.get("email"):
            return False
        account.email = str(found["email"])[:120]
        account.name = str(found.get("name", ""))[:60]
        return True

    def identify_missing(self) -> None:
        """Fills in the name and email of accounts saved before they were asked for."""
        with self._lock:
            waiting = [a for a in self._accounts.values() if not a.email]
        for account in waiting:
            with self._lock:
                if account.id in self._accounts and self._who(account):
                    if _GENERIC_LABEL.fullmatch(account.label):
                        account.label = (account.email or account.name)[:LABEL_MAX]
                    self._save()

    @staticmethod
    def _clean(label: str) -> str:
        label = " ".join(str(label).split())[:LABEL_MAX]
        if not label:
            raise ValueError("an account needs a name")
        return label

    # ------------------------------------------------------------------ the list

    def add(self, label: str, cookies_text: str) -> dict:
        """A new account from a signed-in session. Raises [CookieProblem] (a sentence for the person) if it is not one."""
        with self._lock:
            label = self._clean(label or "YouTube account")
            login.check_text(cookies_text, now=self._clock())
            account = self._make(label, cookies_text)
            return self._view(account, self._clock())

    def replace_login(self, account_id: str, cookies_text: str) -> None:
        """Signing in again: the new session replaces the old one and clears the trouble."""
        with self._lock:
            account = self._accounts[account_id]
            login.install(str(self._file(account_id)), cookies_text, now=self._clock())
            was_named_by_login = account.label in (account.email, account.name) or bool(_GENERIC_LABEL.fullmatch(account.label))
            if self._who(account) and was_named_by_login:
                account.label = (account.email or account.name)[:LABEL_MAX]
            account.attention = False
            account.blocks = 0
            account.rest_until = 0.0
            account.cap = PACES[account.pace]
            self._save()

    def sign_out(self, account_id: str) -> bool:
        with self._lock:
            if account_id not in self._accounts:
                return False
            del self._accounts[account_id]
            login.remove(str(self._file(account_id)))
            self._save()
            return True

    def rename(self, account_id: str, label: str) -> None:
        with self._lock:
            self._accounts[account_id].label = self._clean(label)
            self._save()

    def set_pace(self, account_id: str, pace: str) -> None:
        if pace not in PACES:
            raise ValueError("pace must be gentle, normal or fast")
        with self._lock:
            account = self._accounts[account_id]
            before = PACES[account.pace]
            account.pace = pace
            # an account that was cut back by refusals stays cut back (but never above its new pace)
            account.cap = PACES[pace] if account.cap >= before else min(account.cap, PACES[pace])
            self._save()

    def has(self, account_id: str) -> bool:
        return account_id in self._accounts

    def path_of(self, account_id: str) -> Path:
        """Where an account's saved sign-in is (for the checks that run yt-dlp with it)."""
        if account_id not in self._accounts:
            raise KeyError(account_id)
        return self._file(account_id)

    # ------------------------------------------------------------------ what is usable now

    def _problem(self, account: Account, now: float) -> str | None:
        """Why an account cannot be used at all (a sentence), or `None`."""
        if account.attention:
            return "YouTube keeps refusing this account. Sign in again."
        try:
            login.check_text(self._file(account.id).read_text(encoding="utf-8", errors="replace"), now=now)
        except OSError:
            return "The sign-in is missing. Sign in again."
        except CookieProblem as problem:
            if "run out" in problem.message:
                return "The sign-in has run out. Sign in again."
            return "The sign-in is no longer valid. Sign in again."
        return None

    def _usable(self, account: Account, now: float) -> bool:
        return self._problem(account, now) is None and now >= account.rest_until

    def _effective_cap(self, account: Account, now: float) -> int:
        """The songs an hour this account allows itself: less after a refusal, creeping back an hour at a time."""
        ceiling = PACES[account.pace]
        if account.cap < ceiling and now - account.last_refusal >= 3600:
            account.cap = min(ceiling, int(account.cap * 1.3) + 1)
            account.last_refusal = now  # the next step back is an hour later
        return account.cap

    def _uses_since(self, account_id: str, seconds: float, now: float, what: str = "use") -> int:
        horizon = now - seconds
        return sum(1 for stamp, who, kind in self._events if who == account_id and kind == what and stamp >= horizon)

    def capacity(self) -> int | None:
        """The songs an hour all the usable accounts allow together, or `None` when no account can be used (a visitor)."""
        self._adopt_waiting()
        with self._lock:
            now = self._clock()
            usable = [a for a in self._accounts.values() if self._usable(a, now)]
            if not usable:
                return None
            return sum(self._effective_cap(a, now) for a in usable)

    # ------------------------------------------------------------------ the work

    def lease(self, count: bool = True) -> Lease:
        """The cookies for one yt-dlp run. [count] is `False` for lookups (a search, a playlist listing) that are not a
        song fetched and so do not use up the hourly allowance."""
        self._adopt_waiting()
        with self._lock:
            now = self._clock()
            best, best_key = None, None
            for account in self._accounts.values():
                if not self._usable(account, now):
                    continue
                room = self._effective_cap(account, now) - self._uses_since(account.id, 3600, now)
                if count and room <= 0:
                    continue
                key = (-room, self._last_use.get(account.id, 0.0))
                if best_key is None or key < best_key:
                    best, best_key = account, key
            if best is None:
                return Lease()
            if count:
                self._record(best.id, "use")
                self._last_use[best.id] = now
            return Lease(["--cookies", str(self._file(best.id))], best.id, self._outcome)

    def _outcome(self, account_id: str, outcome: str) -> None:
        """How a run went. `"blocked"`: YouTube refused this account. Anything else: YouTube answered normally."""
        with self._lock:
            account = self._accounts.get(account_id)
            if account is None:
                return
            now = self._clock()
            if outcome != "blocked":
                if account.blocks:
                    account.blocks = 0
                    self._save()
                return
            if now < account.rest_until:
                return  # songs that were already in flight when the first refusal came: one event, not several
            account.blocks += 1
            rest = min(REST_BASE_S * 2 ** (account.blocks - 1), REST_MAX_S)
            account.rest_until = now + rest
            ceiling = PACES[account.pace]
            cap = self._effective_cap(account, now)
            if now - account.last_shrink >= 600:
                account.cap = max(min(60, ceiling), int(cap * 0.7))
                account.last_shrink = now
            account.last_refusal = now
            if account.blocks >= ATTENTION_AFTER:
                account.attention = True
            self._record(account_id, "blocked")
            self._save()
            log.warning("YouTube refused the account %s (%s): resting %.0f s%s", account_id, account.label, rest,
                        ", asks for a new sign-in" if account.attention else "")

    # ------------------------------------------------------------------ what the owner sees

    def _view(self, account: Account, now: float) -> dict:
        problem = self._problem(account, now)
        resting = problem is None and now < account.rest_until
        state = "needs_you" if problem else "resting" if resting else "working"
        out = {
            "id": account.id, "label": account.label, "state": state, "pace": account.pace,
            "perHourAllowed": self._effective_cap(account, now), "signedInSince": int(account.added),
            "thisHour": self._uses_since(account.id, 3600, now), "day": self._uses_since(account.id, 86400, now),
            "refusalsDay": self._uses_since(account.id, 86400, now, "blocked"),
        }
        if account.email:
            out["email"] = account.email
        if account.name:
            out["name"] = account.name
        if problem:
            out["message"] = problem
        elif resting:
            out["restUntil"] = int(account.rest_until)
            out["message"] = "YouTube asked this account to slow down. It carries on by itself."
        try:
            report = login.check_text(self._file(account.id).read_text(encoding="utf-8", errors="replace"), now=now)
            if report.expires:
                out["expires"] = report.expires
        except (OSError, CookieProblem):
            pass
        return out

    def summary(self) -> dict:
        self._adopt_waiting()
        with self._lock:
            now = self._clock()
            cards = [self._view(a, now) for a in sorted(self._accounts.values(), key=lambda a: a.added)]
            usable = [c for c in cards if c["state"] != "needs_you"]
            return {"accounts": cards, "signedIn": bool(usable), "perHour": self.capacity()}
