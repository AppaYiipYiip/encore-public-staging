#!/usr/bin/env python3
"""Measures the documentation against its own rules (docs/README.md says what the rules are). REPORT ONLY today: it prints the baseline and exits 0.

    python tools/check_docs.py            report
    python tools/check_docs.py --strict   exit 1 when any rule is broken (the day the baseline is clean; not yet)
    python tools/check_docs.py --strict-rules map,links   exit 1 only for these rules (CI uses this: a new file must be in the map, no link may break)

What it looks at, for every tracked markdown file:
  map      every file is listed in the map of docs/README.md with its kind, and every listed file exists
  size     a file longer than SIZE_LIMIT words (history, evidence and decisions are exempt: they are logs, not reading)
  stories  dated narrative ("owner, 2026-10-24", "Done so far", "superseded") per 1,000 words in a TRUTH file: truth is written in the present
           tense; a story belongs in the decision log, the board's notes or docs/history
  links    a relative markdown link that points at nothing
  mentions a `file.md` written in backticks that is not a tracked file (a moved or deleted document that is still being cited)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = "docs/README.md"
KINDS = ("entry", "truth", "decision", "plan", "history", "evidence", "guide", "record", "policy", "legacy", "meta")
SIZE_LIMIT = 4500
SIZE_EXEMPT = {"history", "evidence", "decision", "legacy"}
STORY_LIMIT = 4.0   # dated or narrative markers per 1,000 words, in a truth file

DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b|\b\d{1,2} (?:Oct|Nov)(?:ober|ember)? 20\d\d\b|\b(?:Oct|Nov)(?:ober|ember)? \d{1,2}\b")
STORY = re.compile(r"\b(?:Done so far|Status \d|superseded|SUPERSEDED|retraction|Retraction|was wrong|Moved up|moved up|\(checked|Built, not walked|built, not walked|walked on|owner, 20\d\d|Owner, 20\d\d)")
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([a-z]+)\s*\|")
MENTION = re.compile(r"`([A-Za-z0-9_./-]+\.md)`")
#: Documents that live outside the repository on purpose (they name the owner's machines): mentioning them is fine.
OUTSIDE = {"STATUS-2026-10-23.md", "YOUR-NEXT-STEPS.md", "ENCORE-PROJECT-BOOK-2026-11-03.md", "NEXT.md", "ROUND2-LOG.md", "credentials-map.md", "CLAUDE.md"}


ARCHIVED = re.compile(r"^## .*· (\S+\.md)\s*$", re.M)


def archived_names(files: list[str]) -> set[str]:
    """Old file names that now head a section of an archive file (docs/evidence/README.md, docs/history/*.md): citations of them still resolve."""
    names: set[str] = set()
    for f in files:
        if f == "docs/evidence/README.md" or f.startswith("docs/history/"):
            names.update(ARCHIVED.findall((ROOT / f).read_text(encoding="utf-8", errors="replace")))
    return names


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


def read_map(text: str) -> dict[str, str]:
    begin, end = text.find("<!-- map:begin -->"), text.find("<!-- map:end -->")
    if begin < 0 or end < 0:
        return {}
    rows: dict[str, str] = {}
    for line in text[begin:end].splitlines():
        m = ROW.match(line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def broken_links(path: str, text: str) -> list[str]:
    here = (ROOT / path).parent
    bad = []
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        for target in LINK.findall(line):
            if re.match(r"^(?:[a-z]+:|#|mailto:)", target):
                continue
            file = target.split("#", 1)[0]
            if file and not (here / file).resolve().exists():
                bad.append(target)
    return bad


def main(argv: list[str]) -> int:
    files = tracked()
    readme_text = (ROOT / README).read_text(encoding="utf-8") if (ROOT / README).exists() else ""
    mapped = read_map(readme_text)
    problems: dict[str, list[str]] = {"map": [], "size": [], "stories": [], "links": [], "mentions": []}
    known = set(files)
    old_names = archived_names(files)

    for f in files:
        if f not in mapped:
            problems["map"].append(f"{f}: not in the map of {README}")
    for f in mapped:
        if f not in files:
            problems["map"].append(f"{f}: in the map but not a tracked file")
    for f, kind in mapped.items():
        if kind not in KINDS:
            problems["map"].append(f"{f}: the kind '{kind}' is not one of {', '.join(KINDS)}")

    words_total = 0
    for f in files:
        text = (ROOT / f).read_text(encoding="utf-8", errors="replace")
        words = len(text.split())
        words_total += words
        kind = mapped.get(f, "?")
        if words > SIZE_LIMIT and kind not in SIZE_EXEMPT:
            problems["size"].append(f"{f}: {words} words (limit {SIZE_LIMIT}; kind {kind})")
        if kind == "truth":
            markers = (len(DATE.findall(text)) + len(STORY.findall(text))) * 1000 / max(words, 1)
            if markers > STORY_LIMIT:
                problems["stories"].append(f"{f}: {markers:.1f} dated or narrative markers per 1,000 words (limit {STORY_LIMIT})")
        for target in broken_links(f, text):
            problems["links"].append(f"{f}: link to {target} points at nothing")
        for mention in sorted(set(MENTION.findall(text))):
            base = mention.rsplit("/", 1)[-1]
            if base in OUTSIDE or base in old_names or "*" in mention:
                continue
            here = (ROOT / f).parent
            if any(k == mention or k.endswith("/" + mention) for k in known) or (here / mention).resolve().exists() or (ROOT / "docs" / mention).resolve().exists():
                continue
            problems["mentions"].append(f"{f}: mentions `{mention}`, which is not a tracked file")

    print(f"{len(files)} tracked markdown files, {words_total:,} words; {len(mapped)} in the map")
    kinds: dict[str, int] = {}
    for kind in mapped.values():
        kinds[kind] = kinds.get(kind, 0) + 1
    print("  by kind: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    total = 0
    for name, items in problems.items():
        total += len(items)
        print(f"\n{name}: {len(items)}")
        for item in items[:60]:
            print(f"  {item}")
        if len(items) > 60:
            print(f"  ... and {len(items) - 60} more")
    strict: set[str] = set()
    if "--strict-rules" in argv:
        i = argv.index("--strict-rules")
        if i + 1 < len(argv):
            strict = set(argv[i + 1].split(","))
    failing = total if "--strict" in argv else sum(len(problems[r]) for r in strict if r in problems)
    print(f"\n{total} problem(s). " + (f"{failing} in a strict rule: this fails." if failing else "Nothing in a strict rule; the rest only reports."))
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
