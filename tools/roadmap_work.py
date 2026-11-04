#!/usr/bin/env python3
"""Who is working on what, right now: the "Working now" part of the roadmap board (and of `python tools/roadmap.py brief`).

Two sources, shown together, so nobody has to remember to keep a list up to date:

1. CLAIMS: what an agent or a person announces ("I am on P2-22: the notification ask; if I stop: the tests exist, the code does not").
   One small file per claim in the git common directory (`<clone>/.git/encore-working/`). Every worktree of this clone resolves the same folder, so the two
   Claude accounts and the owner on this PC see each other at once, with nothing to commit or merge. They are never pushed. Without git, `.encore-working/`
   in the root (git-ignored) is used. A claim that has not been touched for STALE_HOURS is shown as "maybe stopped" (a usage limit looks exactly like that
   from outside); it is never deleted for being old, only when its author says `done`.
2. GITHUB: the open pull requests (draft or not) and their branches, matched to items by the id in the branch name or the title (task/P2-22-...). This is how a
   developer on another computer shows up without any extra step: opening a draft PR early IS the announcement.

A claim is information for the others, not a lock: two people can still work on the same item, but they will see each other first.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import roadmap_notes as rn

DIRNAME = "encore-working"
FALLBACK = ".encore-working"
STALE_HOURS = 8
KEEP_DONE_DAYS = 3
STATUSES = ("active", "paused", "done")
MAX_DOING, MAX_STATE = 200, 600
ID_IN_TEXT = re.compile(r"\b(P\d-\d+[a-z]?|N-\d+)\b")


def work_dir(root: Path, runner=subprocess.run) -> Path:
    """The shared folder of this clone (all its worktrees), or a git-ignored folder in the root when there is no git."""
    try:
        r = runner(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip()) / DIRNAME
    except (OSError, subprocess.SubprocessError):
        pass
    return root / FALLBACK


def git_pending(root: Path, runner=subprocess.run) -> list[str] | None:
    """Uncommitted changes under docs/roadmap (the order the owner dragged, notes written on the board): the first thing the next session must turn
    into a docs PR. [] when there are none, None when git is not available."""
    try:
        r = runner(["git", "status", "--porcelain", "--untracked-files=all", "--", "docs/roadmap"], cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return [ln.rstrip() for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else None


def git_branch(root: Path, runner=subprocess.run) -> str:
    try:
        r = runner(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _write(d: Path, claim: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".claim-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(claim, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, d / f"{claim['id']}.json")


def _check(items: list[str], doing: str, state: str, known: set[str] | None) -> None:
    if not items:
        raise rn.NoteError("name at least one item (P2-22, N-04) or _board")
    for it in items:
        if not rn.ITEM_RE.match(it) or (known is not None and it != rn.BOARD and it not in known):
            raise rn.NoteError(f"{it} is not an item of the plan")
    if not doing.strip() or len(doing) > MAX_DOING:
        raise rn.NoteError(f"say in a few words what you are doing (1 to {MAX_DOING} characters)")
    if len(state) > MAX_STATE:
        raise rn.NoteError(f"the hand-over text is too long (limit {MAX_STATE})")
    why = rn.looks_secret(doing) or rn.looks_secret(state)
    if why:
        raise rn.NoteError(f"this looks like {why}; nothing secret goes in a claim")


def start(root: Path, role: str, by: str, items: list[str], doing: str, state: str = "", branch: str = "", pr: str = "",
          known_items: set[str] | None = None, now: datetime | None = None, wdir: Path | None = None) -> dict:
    if role not in rn.ROLES:
        raise rn.NoteError(f"the role must be one of {', '.join(rn.ROLES)}")
    by = (by or "").strip()
    if not by or len(by) > rn.MAX_BY:
        raise rn.NoteError(f"say who you are (1 to {rn.MAX_BY} characters)")
    items = list(dict.fromkeys(items))
    _check(items, doing, state, known_items)
    now = now or rn.now_utc()
    c = {"id": f"{rn.stamp(now)}-{role}-{secrets.token_hex(2)}", "role": role, "by": by, "items": items, "doing": doing.strip(), "state": state.strip(),
         "branch": branch.strip(), "pr": pr.strip(), "started": _iso(now), "updated": _iso(now), "status": "active"}
    _write(wdir or work_dir(root), c)
    return c


def _read(d: Path) -> list[dict]:
    out = []
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(c, dict) and c.get("status") in STATUSES and isinstance(c.get("items"), list) and c.get("id") == f.stem:
                out.append(c)
        except (OSError, ValueError):
            continue                                   # a half-written or foreign file never breaks the page
    return out


def list_claims(root: Path, now: datetime | None = None, wdir: Path | None = None) -> list[dict]:
    """Active and paused claims (newest update first) plus what finished in the last KEEP_DONE_DAYS; old finished ones are removed."""
    d = wdir or work_dir(root)
    now = now or rn.now_utc()
    out = []
    for c in _read(d):
        age = now - _parse(c["updated"])
        if c["status"] == "done":
            if age > timedelta(days=KEEP_DONE_DAYS):
                try:
                    (d / f"{c['id']}.json").unlink()
                except OSError:
                    pass
                continue
        c = dict(c)
        c["hours_quiet"] = round(age.total_seconds() / 3600, 1)
        c["maybe_stopped"] = c["status"] != "done" and age > timedelta(hours=STALE_HOURS)
        out.append(c)
    out.sort(key=lambda c: c["updated"], reverse=True)          # newest update first ...
    out.sort(key=lambda c: c["status"] == "done")               # ... and what finished goes below what is live (the sort is stable)
    return out


def find(root: Path, ref: str, by: str = "", wdir: Path | None = None) -> dict:
    """A claim by its id, or the one live claim for an item (and an author, when several people are on it)."""
    live = [c for c in _read(wdir or work_dir(root)) if c["status"] != "done"]
    exact = [c for c in live if c["id"] == ref]
    if exact:
        return exact[0]
    hits = [c for c in live if ref in c["items"] and (not by or c["by"] == by)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise rn.NoteError(f"no live claim for {ref}" + (f" by {by}" if by else ""))
    raise rn.NoteError(f"{len(hits)} live claims for {ref}; pass the claim id: " + ", ".join(c["id"] for c in hits))


def update(root: Path, ref: str, by: str = "", doing: str | None = None, state: str | None = None, branch: str | None = None, pr: str | None = None,
           status: str | None = None, known_items: set[str] | None = None, now: datetime | None = None, wdir: Path | None = None) -> dict:
    d = wdir or work_dir(root)
    c = dict(find(root, ref, by, d))
    if status is not None and status not in STATUSES:
        raise rn.NoteError(f"the status must be one of {', '.join(STATUSES)}")
    for k, v in (("doing", doing), ("state", state), ("branch", branch), ("pr", pr), ("status", status)):
        if v is not None:
            c[k] = v.strip()
    _check(c["items"], c["doing"], c["state"], known_items)
    c["updated"] = _iso(now or rn.now_utc())
    _write(d, c)
    return c


def finish(root: Path, ref: str, by: str = "", result: str = "", **kw) -> dict:
    """Mark a claim done; `result` replaces the hand-over text (what happened, where the work is: the PR, the branch)."""
    return update(root, ref, by=by, state=result or None, status="done", **kw)


# ------------------------------------------------------------------------------------------------------------------ GitHub
_CACHE: dict[str, tuple[float, list[dict]]] = {}


def github_prs(root: Path, runner=subprocess.run, ttl: float = 60.0, clock=time.monotonic) -> list[dict] | None:
    """Open pull requests, or None when `gh` is missing, not signed in or offline (the page then just leaves the list out). Cached for `ttl` seconds."""
    key = str(root)
    hit = _CACHE.get(key)
    if hit and clock() - hit[0] < ttl:
        return hit[1]
    try:
        r = runner(["gh", "pr", "list", "--state", "open", "--limit", "40", "--json", "number,title,headRefName,author,isDraft,updatedAt,url"],
                   cwd=root, capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        raw = json.loads(r.stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    prs = []
    for p in raw:
        text = f"{p.get('headRefName', '')} {p.get('title', '')}"
        prs.append({"number": p.get("number"), "title": p.get("title", ""), "branch": p.get("headRefName", ""), "draft": bool(p.get("isDraft")),
                    "author": (p.get("author") or {}).get("login", ""), "updated": p.get("updatedAt", ""), "url": p.get("url", ""),
                    "items": sorted(set(ID_IN_TEXT.findall(text)))})
    _CACHE[key] = (clock(), prs)
    return prs
