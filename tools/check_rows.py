#!/usr/bin/env python3
"""Which rows of the state tables (docs/31 to 34) marked Built have a test? (docs/11 ADR-R41 T2)

    python -I tools/check_rows.py                 print, per table, the Built rows that have no test at all
    python -I tools/check_rows.py --max-missing N exit 1 when more than N Built rows have none (the ratchet: N may only go down)

A Built row has a test when (a) its id (`CN-11`, `AC-3`, `PB-12`, `CF-7`...) appears as a whole word in a test file (in a test's name or group:
`'CN-11: an impostor at the saved address is never sent a login'`), or (b) a test file that the row lists in its Tests column exists, or a test name it quotes in backticks appears in a test file.
(a) is the goal, because it says which promise a test keeps; (b) is what the tables have today. Test files searched: `*_test.dart` under app/
and packages/, `test_*.py` under server/. Open questions (`O-n`) and gaps (`G-n`) are not rows of behaviour and are skipped.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TABLES = ["31-connecting-to-a-server.md", "32-accounts-joining-and-devices.md", "33-playback-sources-states-and-failures.md", "34-conflicts-and-offline-edits.md"]
ROW = re.compile(r"^\|\s*((?:CN|AC|IV|JN|DV|PB|CF)-F?\d+[a-z]?)\s*\|")
BUILT = re.compile(r"\bBuilt\b")
PHRASE = re.compile(r"`([^`]{15,})`")
LISTED = re.compile(r"`([\w./-]*(?:_test\.dart|test_\w+\.py))`")
TEST_GLOBS = ("app/test/**/*_test.dart", "packages/*/test/**/*_test.dart", "server/**/test_*.py")


def rows(table):
    """id -> (is Built, test file names the row lists, quoted phrases the row lists)"""
    found = {}
    for line in (REPO / "docs" / table).read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            found[m.group(1)] = (bool(BUILT.search(line)), [Path(f).name for f in LISTED.findall(line)],
                                 [p for p in PHRASE.findall(line) if " " in p and not LISTED.fullmatch("`" + p + "`")])
    return found


def test_files():
    return [path for pattern in TEST_GLOBS for path in REPO.glob(pattern)]


def main():
    limit = int(sys.argv[sys.argv.index("--max-missing") + 1]) if "--max-missing" in sys.argv else None
    files = test_files()
    existing = {path.name for path in files}
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in files)
    built_total = named_total = bare_total = 0
    for table in TABLES:
        found = rows(table)
        built = [r for r, (is_built, _names, _phrases) in found.items() if is_built]
        named = [r for r in built if re.search(rf"\b{re.escape(r)}\b", text)]
        listed = [r for r in built if r not in named and (any(n in existing for n in found[r][1]) or any(p in text for p in found[r][2]))]
        bare = [r for r in built if r not in named and r not in listed]
        built_total += len(built)
        named_total += len(named)
        bare_total += len(bare)
        print(f"{table}: {len(built)} Built rows; {len(named)} named by a test, {len(listed)} only list a test that exists, {len(bare)} have neither")
        if bare:
            print("    neither: " + " ".join(bare))
    print(f"total: {built_total} Built rows, {named_total} named by a test, {bare_total} with no test at all")
    if limit is not None and bare_total > limit:
        print(f"more than {limit}: a row was marked Built without a test, or its test file went")
        sys.exit(1)


if __name__ == "__main__":
    main()
