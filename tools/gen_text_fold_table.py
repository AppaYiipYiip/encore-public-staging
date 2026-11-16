#!/usr/bin/env python3
"""Writes the phone's copy of the text fold (P2-25, audit B-37) from Python's own Unicode data, so the server and the phone cannot disagree.

    python -X utf8 tools/gen_text_fold_table.py            # rewrites app/lib/domain/text_fold_table.g.dart and the `corpus` section of the shared fixture
    python -X utf8 tools/gen_text_fold_table.py --check    # exits 1 when either file is not what this Python says now (the server workflow runs it)

**Run it with the Python the server runs on.** The tables are data of one Unicode version, `textnorm.UNICODE_VERSION` (15.0.0: Python 3.12, which is
what `server.yml` and the `python:3.12-slim` image run). The tool REFUSES to write or to check unless `unicodedata.unidata_version` equals the version
named in `textnorm.py`, in the fixture's header and (for `--check`) in the committed table: a developer whose Python is newer runs it with a 3.12
interpreter (`uv python install 3.12`; `uv run --python 3.12 python -X utf8 tools/gen_text_fold_table.py`). The fixture's header (`revision`,
`unidata_version`) is written by hand, on purpose: bumping them is the deliberate act, and the tool then agrees or refuses.

What it writes:
* `app/lib/domain/text_fold_table.g.dart`: the tables `app/lib/domain/text_fold.dart` needs and the phone's Dart cannot get at the pinned version (it has no
  NFKC, no full case fold, and its own Unicode version): canonical and compatibility decompositions, combining classes, composition pairs, case fold,
  the letter, number and mark classes, the decimal digits, the format characters, plus the hand-chosen rules of `textnorm.py` (the marks to remove, the
  protected letters, the letter table), so `textnorm.py` stays the one place a rule is written.
* the `corpus` section of `app/test/fixtures/text/fold-cases.json`: digests of the fold of every code point and of 20,000 random strings
  (`server/encore_server/tests/textfold_corpus.py` says how), which both test suites check. The rows of the fixture are written by hand and are never touched.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server" / "encore_server"))

from encore_server import textnorm  # noqa: E402
from tests import textfold_corpus as corpus  # noqa: E402

FIXTURE = ROOT / "app" / "test" / "fixtures" / "text" / "fold-cases.json"
TARGET = ROOT / "app" / "lib" / "domain" / "text_fold_table.g.dart"

HANGUL = (0xAC00, 0xD7A3)  # composed and decomposed by arithmetic, not by a table
SEED = 20261115
COUNT = 20_000
MAX_LENGTH = 8

#: Where the random strings of the corpus come from: bases and marks of every script the fold has a rule for, in the orders that go wrong (a base that
#: changes after its mark, a format character in the middle, marks in a row). Hand-chosen; the fixture records it.
POOL = (
    "abceinosuxzAEISZ0123-_ !$'.’–/\u3000\u00a0"
    "ıİłøßẞđðþæœħŧ"
    "\u0300\u0301\u0302\u0303\u0304\u0306\u0307\u0308\u030a\u030c\u0323\u0327\u0328\u031b\u0338\u0342\u0345"
    "ابتكلمنهويءةىیکےۀہؤئأإآٱـ"
    "\u064b\u064e\u064f\u0650\u0651\u0652\u0653\u0654\u0655\u0670\u06d6"
    "שלום\u05b0\u05b4\u05b8\u05b9\u05bc\u05c1\u05c2"
    "कतमह\u093c\u093f\u0941\u094d\u0902\u094bक़"
    "กสวด\u0e31\u0e48\u0e49ำ\u0e4d\u0e35"
    "각힝가한글각"
    "かが\u3099\u309aハばぱカｶﾞﾟー"
    "ийеёуўїі"
    "αειουςσΣάΐᾳ"
    "٣۳३๓٠１"
    "\u200b\u200c\u200d\u200e\u200f\u202a\u202e\u2060\u061c\ufeff\u00ad"
    "ﬃＡｂ①²½㎏Ǆǅﷲﻻﻓﻴ㈱℡Ⅻẛŉǰ"
    "\U0001f3b5\ufe0f\u20e3"
)
POOL_CODE_POINTS = [ord(ch) for ch in POOL]


class Refusal(SystemExit):
    pass


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the tables

def _hex(cp: int) -> str:
    return f"{cp:x}"


def _is_hangul(cp: int) -> bool:
    return HANGUL[0] <= cp <= HANGUL[1]


def _code_points() -> range:
    return range(0x110000)


def _entries(mapping: dict[int, list[int]]) -> str:
    """`cp:cp,cp` per entry, and `lo-hi:target` for a run of code points that map to consecutive single code points; entries are separated by a space."""
    items = sorted(mapping.items())
    out: list[str] = []
    i = 0
    while i < len(items):
        cp, value = items[i]
        j = i
        if len(value) == 1:
            while (
                j + 1 < len(items)
                and items[j + 1][0] == items[j][0] + 1
                and len(items[j + 1][1]) == 1
                and items[j + 1][1][0] == items[j][1][0] + 1
            ):
                j += 1
        if j > i:
            out.append(f"{_hex(cp)}-{_hex(items[j][0])}:{_hex(value[0])}")
        else:
            out.append(f"{_hex(cp)}:" + ",".join(_hex(v) for v in value))
        i = j + 1
    return " ".join(out)


def _ranges(predicate: Callable[[str], bool]) -> str:
    out: list[list[int]] = []
    for cp in _code_points():
        if 0xD800 <= cp <= 0xDFFF:
            continue
        if predicate(chr(cp)):
            if out and out[-1][1] == cp - 1:
                out[-1][1] = cp
            else:
                out.append([cp, cp])
    return " ".join(_hex(a) if a == b else f"{_hex(a)}-{_hex(b)}" for a, b in out)


def build_tables() -> dict[str, str]:
    canon: dict[int, list[int]] = {}
    compat: dict[int, list[int]] = {}
    casefold: dict[int, list[int]] = {}
    comp: dict[int, list[int]] = {}
    ccc: list[list[int]] = []
    for cp in _code_points():
        if 0xD800 <= cp <= 0xDFFF or _is_hangul(cp):
            continue
        ch = chr(cp)
        nfd = unicodedata.normalize("NFD", ch)
        nfkd = unicodedata.normalize("NFKD", ch)
        if nfd != ch:
            canon[cp] = [ord(c) for c in nfd]
        if nfkd != nfd:
            compat[cp] = [ord(c) for c in nfkd]
        folded = ch.casefold()
        if folded != ch:
            casefold[cp] = [ord(c) for c in folded]
        decomposition = unicodedata.decomposition(ch)
        if decomposition and not decomposition.startswith("<"):
            parts = [int(x, 16) for x in decomposition.split()]
            # a primary composite: the pair composes back to it (composition exclusions, singletons and non-starter decompositions do not)
            if len(parts) == 2 and unicodedata.normalize("NFC", ch) == ch:
                comp[cp] = parts
        klass = unicodedata.combining(ch)
        if klass:
            if ccc and ccc[-1][1] == cp - 1 and ccc[-1][2] == klass:
                ccc[-1][1] = cp
            else:
                ccc.append([cp, cp, klass])
    zeros: list[int] = []
    for cp in _code_points():
        if 0xD800 <= cp <= 0xDFFF or unicodedata.category(chr(cp)) != "Nd":
            continue
        value = unicodedata.decimal(chr(cp))
        if value == 0:
            zeros.append(cp)
        # every Nd code point must sit in a run of ten that starts at a zero (the phone finds a digit by `cp - zero`)
        zero = max(z for z in zeros if z <= cp)
        if cp - zero != value or cp - zero > 9:
            raise Refusal(f"decimal digit U+{cp:04X} is not in a run of ten from a zero: the digit table needs another shape")
    return {
        "canon": _entries(canon),
        "compat": _entries(compat),
        "fold": _entries(casefold),
        "ccc": " ".join(f"{_hex(a)}-{_hex(b)}:{c}" if a != b else f"{_hex(a)}:{c}" for a, b, c in ccc),
        "comp": " ".join(f"{_hex(a)},{_hex(b)}:{_hex(cp)}" for cp, (a, b) in sorted(comp.items(), key=lambda kv: (kv[1], kv[0]))),
        "letters": _ranges(lambda c: unicodedata.category(c)[0] == "L"),
        "numbers": _ranges(lambda c: unicodedata.category(c)[0] == "N"),
        "marks": _ranges(lambda c: unicodedata.category(c)[0] == "M"),
        "format": _ranges(lambda c: unicodedata.category(c) == "Cf"),
        "zeros": " ".join(_hex(z) for z in zeros),
        # the hand-chosen rules, from the one place they are written
        "marks_out": " ".join(f"{_hex(a)}-{_hex(b)}" if a != b else _hex(a) for a, b in sorted(textnorm.DECORATING_MARKS)),
        "protected": " ".join(_hex(ord(c)) for c in textnorm.PROTECTED_LETTERS),
        "before_marks": _entries({k: [ord(c) for c in v] for k, v in textnorm._BEFORE_MARKS.items()}),
        "letter_table": _entries({k: [ord(c) for c in v] for k, v in textnorm.FOLDED_LETTERS.items()}),
    }


_DOC = {
    "canon": "Full canonical decomposition (NFD) of every code point it changes, except Hangul syllables (arithmetic).",
    "compat": "Full compatibility decomposition (NFKD) of every code point whose NFKD is not its NFD.",
    "fold": "Full case folding (`str.casefold`): the code points it changes.",
    "ccc": "Canonical combining class, `first-last:class` (decimal class).",
    "comp": "Primary composites: `first,second:composite` (a pair that composes; exclusions are not here).",
    "letters": "General category L*, as ranges.",
    "numbers": "General category N*, as ranges.",
    "marks": "General category M*, as ranges.",
    "format": "General category Cf, as ranges (removed; U+200C is a space).",
    "zeros": "The code point of the digit zero of every run of ten decimal digits (category Nd).",
    "marks_out": "The decorating marks that are removed (textnorm.DECORATING_MARKS).",
    "protected": "The letters that are not an accent on another letter (textnorm.PROTECTED_LETTERS).",
    "before_marks": "Mapped before the marks are removed (textnorm._BEFORE_MARKS).",
    "letter_table": "Letters with no decomposition that are written as another letter, and the tatweel (textnorm.FOLDED_LETTERS).",
}
_NAMES = {
    "canon": "kTextFoldCanon",
    "compat": "kTextFoldCompat",
    "fold": "kTextFoldCase",
    "ccc": "kTextFoldCombining",
    "comp": "kTextFoldComposition",
    "letters": "kTextFoldLetters",
    "numbers": "kTextFoldNumbers",
    "marks": "kTextFoldMarks",
    "format": "kTextFoldFormat",
    "zeros": "kTextFoldDigitZeros",
    "marks_out": "kTextFoldMarksOut",
    "protected": "kTextFoldProtected",
    "before_marks": "kTextFoldBeforeMarks",
    "letter_table": "kTextFoldLetterTable",
}


def _dart_string(name: str, body: str, width: int = 96) -> str:
    chunks = [body[i : i + width] for i in range(0, len(body), width)] or [""]
    if len(chunks) == 1:
        return f"const String {name} = '{chunks[0]}';\n"
    lines = "\n".join(f"    '{chunk}'" for chunk in chunks)
    return f"const String {name} =\n{lines};\n"


def render_table() -> str:
    tables = build_tables()
    head = (
        "// GENERATED CODE - DO NOT MODIFY BY HAND.\n"
        "//\n"
        "// Written by tools/gen_text_fold_table.py from Python's unicodedata (Unicode " + textnorm.UNICODE_VERSION + ") and from the rules of\n"
        "// server/encore_server/encore_server/textnorm.py, so that the phone and the server fold text the same way (P2-25, audit B-37). Read by\n"
        "// text_fold.dart. `python -X utf8 tools/gen_text_fold_table.py --check` fails when this file is not what the tool writes (the server workflow).\n"
        "// Code points are lower-case hex; `a-b` is a range; a mapping `a-b:c` sends a to c, a+1 to c+1 and so on.\n"
        "//\n"
        "// dart format off\n"
        "library;\n\n"
        f"/// The Unicode version of every table below (Python's `unicodedata.unidata_version` when it was written).\n"
        f"const String kTextFoldUnidataVersion = '{textnorm.UNICODE_VERSION}';\n\n"
        "/// The revision of the fold (`textnorm.TEXTNORM_REVISION`): the fixture names the same number.\n"
        f"const int kTextFoldRevision = {textnorm.TEXTNORM_REVISION};\n"
    )
    parts = [head]
    for key in _NAMES:
        parts.append(f"\n/// {_DOC[key]}\n" + _dart_string(_NAMES[key], tables[key]))
    return "".join(parts)


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the fixture

_FLAGGED = {"Cc", "Cf", "Zs", "Zl", "Zp", "Co", "Cs", "Cn", "Mn", "Mc", "Me"}


def _escape(text: str) -> str:
    """JSON text with every invisible, combining or unassigned character written as `\\uXXXX`, so a reviewer sees which code point a row means."""
    out: list[str] = []
    for ch in text:
        if ord(ch) > 0x7F and unicodedata.category(ch) in _FLAGGED:
            cp = ord(ch)
            if cp > 0xFFFF:
                cp -= 0x10000
                out.append(f"\\u{0xD800 + (cp >> 10):04x}\\u{0xDC00 + (cp & 0x3FF):04x}")
            else:
                out.append(f"\\u{cp:04x}")
        else:
            out.append(ch)
    return "".join(out)


def _row(value: object) -> str:
    return _escape(json.dumps(value, ensure_ascii=False))


def _rows(rows: list[object], indent: str) -> str:
    if not rows:
        return "[]"
    return "[\n" + ",\n".join(f"{indent} {_row(r)}" for r in rows) + f"\n{indent}]"


def corpus_section() -> dict[str, object]:
    return {
        "unidata_version": textnorm.UNICODE_VERSION,
        "page": corpus.PAGE,
        "fold_pages": corpus.fold_pages(textnorm.fold),
        "class_pages": corpus.class_pages(),
        "random": {
            "seed": SEED,
            "count": COUNT,
            "max_length": MAX_LENGTH,
            "pool": POOL_CODE_POINTS,
            "digest": corpus.random_digest(textnorm.fold, textnorm.words, POOL_CODE_POINTS, SEED, COUNT, MAX_LENGTH),
        },
    }


def render_fixture(data: dict[str, object]) -> str:
    data = dict(data)
    data["corpus"] = corpus_section()
    c = data.pop("corpus")
    assert isinstance(c, dict)
    rnd = c["random"]
    pool = rnd["pool"]
    pool_lines = ",\n".join("   " + ", ".join(str(cp) for cp in pool[i : i + 16]) for i in range(0, len(pool), 16))
    parts: list[str] = []
    for key, value in data.items():
        if isinstance(value, list) and value:
            parts.append(f' "{key}": {_rows(value, " ")}')
        else:
            parts.append(f' "{key}": {_row(value)}')
    corpus_text = (
        ' "corpus": {\n'
        f'  "unidata_version": {_row(c["unidata_version"])},\n'
        f'  "page": {c["page"]},\n'
        f'  "fold_pages": {_rows(c["fold_pages"], "  ")},\n'
        f'  "class_pages": {_rows(c["class_pages"], "  ")},\n'
        '  "random": {\n'
        f'   "seed": {rnd["seed"]},\n'
        f'   "count": {rnd["count"]},\n'
        f'   "max_length": {rnd["max_length"]},\n'
        f'   "digest": {_row(rnd["digest"])},\n'
        '   "pool": [\n'
        f"{pool_lines}\n"
        "   ]\n"
        "  }\n"
        " }"
    )
    parts.append(corpus_text)
    return "{\n" + ",\n".join(parts) + "\n}\n"


# ---------------------------------------------------------------------------------------------------------------------------------------------------

def _refuse_unless_pinned(data: dict[str, object], committed_table: str | None) -> None:
    named = {
        "the running Python (unicodedata.unidata_version)": unicodedata.unidata_version,
        "textnorm.UNICODE_VERSION": textnorm.UNICODE_VERSION,
        "the fixture header (unidata_version)": data.get("unidata_version"),
    }
    if committed_table is not None:
        found = re.search(r"kTextFoldUnidataVersion = '([^']*)'", committed_table)
        named["the committed table (kTextFoldUnidataVersion)"] = found.group(1) if found else None
    if len(set(named.values())) != 1:
        lines = "\n".join(f"  {where}: {version}" for where, version in named.items())
        raise Refusal(
            "refusing: the Unicode versions disagree, so a table written now would not be the one the server and the phone are tested against.\n"
            f"{lines}\nRun the tool with the Python the server runs on (3.12: `uv run --python 3.12 python -X utf8 tools/gen_text_fold_table.py`). "
            "To move to a newer Unicode on purpose, change textnorm.UNICODE_VERSION, TEXTNORM_REVISION and the fixture header together first."
        )
    if data.get("revision") != textnorm.TEXTNORM_REVISION:
        raise Refusal(f"refusing: the fixture says revision {data.get('revision')}, textnorm.TEXTNORM_REVISION is {textnorm.TEXTNORM_REVISION}")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else ""


def main(argv: list[str]) -> int:
    check = "--check" in argv
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _refuse_unless_pinned(data, _read(TARGET) if check else None)
    table = render_table()
    fixture = render_fixture(data)
    if check:
        stale = [name for name, path, wanted in (("the Dart table", TARGET, table), ("the fixture", FIXTURE, fixture)) if _read(path) != wanted]
        if stale:
            print(f"out of date: {' and '.join(stale)}. Run: python -X utf8 tools/gen_text_fold_table.py (with the Python 3.12 the server runs on)", file=sys.stderr)
            return 1
        print("text fold table and fixture are current")
        return 0
    TARGET.write_text(table, encoding="utf-8", newline="\n")
    FIXTURE.write_text(fixture, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT)} ({len(table):,} bytes) and the corpus section of {FIXTURE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
