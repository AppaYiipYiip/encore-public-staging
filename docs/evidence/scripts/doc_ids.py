"""Which identifiers do the documents carry, and did a restructuring lose any? (docs/README.md, D-62)

Code, tests, the board and other documents cite findings, decisions, state rows and tasks by ID (CN-24, PB-F7, CF-20, D-61, ADR-R38, F21, B12, Q30, P2-22 ...).
A document that is merged or shortened must keep every ID somewhere, or the ID must be explained in docs/history/README.md. This script snapshots the IDs and diffs them.

    python docs/evidence/scripts/doc_ids.py snapshot FILE [REV]  write the sorted IDs of every tracked markdown file under docs/ and the root files to FILE
                                                                 (as committed at REV; with no REV: the working tree)
    python docs/evidence/scripts/doc_ids.py diff FILE            print the IDs in FILE that no tracked markdown file carries any more (exit 1 when there are some)
    python docs/evidence/scripts/doc_ids.py counts               how many IDs per prefix (to see what it recognises)

The baseline of the restructuring of 6 Nov 2026 is `doc_ids.baseline.txt`, taken from commit 4f18b3568b (`snapshot doc_ids.baseline.txt 4f18b3568b`).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
# prefix, then digits, then an optional letter: CN-24, PB-F7b, CF-20, DV-3, AC-22, IV-4, JN-2, US-75, D-61, ADR-R38, F21, F-21, B12b, B-37, Q30, R1-6, R2-F3, P2-22, S-71, W-05, X-7, G-1, O-5, H43, A4, E21
TOKEN = re.compile(r"(?<![A-Za-z0-9_/.-])((?:CN|PB|CF|DV|AC|IV|JN|US|ADR|R1|R2|P[0-6])-[FR]?\d+[a-z]?|(?:D|F|B|Q|S|W|X|G|O|H|A|E|J|M|N|C)-?\d{1,3}[a-z]?)(?![A-Za-z0-9_-])")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout


def tracked_markdown(rev: str | None = None) -> list[str]:
    names = (git("ls-tree", "-r", "--name-only", rev) if rev else git("ls-files")).splitlines()
    return [n for n in names if n.endswith(".md") and (n.startswith("docs/") or "/" not in n)]


def ids(rev: str | None = None) -> set[str]:
    found: set[str] = set()
    for name in tracked_markdown(rev):
        text = git("show", f"{rev}:{name}") if rev else (REPO / name).read_text(encoding="utf-8", errors="replace")
        for match in TOKEN.finditer(text):
            # "F-21" and "F21" are one ID: a hyphen between a lone letter and digits is a style
            found.add(re.sub(r"^([A-Z])-(\d)", r"\1\2", match.group(1)))
    return found


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    command = sys.argv[1] if len(sys.argv) > 1 else "counts"
    if command == "snapshot":
        found = ids(sys.argv[3] if len(sys.argv) > 3 else None)
        Path(sys.argv[2]).write_text("\n".join(sorted(found)) + "\n", encoding="utf-8")
        print(f"{len(found)} identifiers written to {sys.argv[2]}")
        return 0
    if command == "diff":
        before = set(Path(sys.argv[2]).read_text(encoding="utf-8").split())
        gone = sorted(before - ids())
        print(f"{len(gone)} identifiers of {len(before)} are no longer in any tracked markdown file")
        for token in gone:
            print(" ", token)
        return 1 if gone else 0
    count = Counter(re.match(r"[A-Za-z]+(?:-[A-Z])?", token).group(0) for token in ids())
    for prefix, number in count.most_common():
        print(f"{number:5d}  {prefix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
