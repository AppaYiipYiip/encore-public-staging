"""The corpus of the shared text-fold fixture (P2-25, `app/test/fixtures/text/fold-cases.json`): what is hashed, and how.

**Test support, read by two programs and re-implemented once.** `tests/test_textnorm.py` checks the committed digests against the running Python;
`tools/gen_text_fold_table.py` writes them; `app/test/domain/text_fold_test.dart` computes the same digests with the phone's fold (the algorithms
below are written in the fixture's `about` so that the Dart copy is a transcription, not a design). A digest that differs is the signal "the fold
changed": bump `textnorm.TEXTNORM_REVISION` (a rekey runs at the next start, slice 3), then run the tool.

* **Pages.** The code space is cut into pages of 256 code points. For every page that holds a code point the fold CHANGES (`fold(chr(cp)) != chr(cp)`),
  the fixture records `[first code point of the page, how many changed, digest]`. The digest is FNV-1a (32 bit) over the UTF-8 bytes of the lines
  `"<code point in lower-case hex>:<fold>\\n"`, in order. A page that is not listed must not hold a changed code point: a newer Unicode that gives an
  unassigned code point a case or a decomposition shows up as a page that is not in the file. Code points that nobody has assigned are skipped by
  Python at once (category `Cn`: the fold never changes them, except inside the ranges of marks it deletes, which are walked), which is what keeps
  this fast; Dart walks every code point.
* **Classes.** The same pages for the three classes `words` reads: for every code point that is a letter (`L*`), a number (`N*`) or a mark (`M*`) the line
  is `"<hex>:<l|n|m>\\n"`.
* **Random strings.** `count` strings of 1 to `max_length` characters out of `pool` (code points), made by xorshift32 from `seed`: `x ^= (x << 13) & M;
  x ^= x >> 17; x ^= (x << 5) & M` (M = 0xFFFFFFFF); the length is `1 + next() % max_length`, each character is `pool[next() % len(pool)]`. The digest is
  over the lines `"<i>:<fold>|<the words joined by />\\n"`. This is what proves the two languages agree on ORDER (marks in a row, a format character in
  the middle, a base that changes after its mark), which no single code point can show.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterator

from encore_server import textnorm

PAGE = 0x100
_MASK = 0xFFFFFFFF
_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193


def fnv1a32(data: bytes, h: int = _FNV_OFFSET) -> int:
    for byte in data:
        h = ((h ^ byte) * _FNV_PRIME) & _MASK
    return h


def _hex(h: int) -> str:
    return f"{h:08x}"


#: Code points that a NEWER Unicode than the pin has assigned, by (the pin, the running version). A developer's Python 3.13 (Unicode 15.1.0) must give the
#: digests of the pin (15.0.0), and it does once these are skipped: proof, run on 7 properties (category, combining class, NFKC, NFD, NFKD,
#: case fold, decimal digit) of every code point of both versions: the ONLY difference between 15.0.0 and 15.1.0 is that these 627 code points are
#: assigned (622 CJK ideographs of Extension I, which are letters, and five symbols). A Python that is neither the pin nor listed here skips nothing:
#: its digests differ and the corpus test says "bump TEXTNORM_REVISION", which is the point of it.
ASSIGNED_AFTER_PIN: dict[tuple[str, str], tuple[tuple[int, int], ...]] = {
    ("15.0.0", "15.1.0"): ((0x2FFC, 0x2FFF), (0x31EF, 0x31EF), (0x2EBF0, 0x2EE5D)),
}


def _skipped() -> tuple[tuple[int, int], ...]:
    return ASSIGNED_AFTER_PIN.get((textnorm.UNICODE_VERSION, unicodedata.unidata_version), ())


def _code_points() -> Iterator[tuple[int, str]]:
    skipped = _skipped()
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        ch = chr(cp)
        if any(lo <= cp <= hi for lo, hi in skipped):
            continue
        # Nobody has assigned it: the fold never changes it, except where a whole range is deleted (the allow-list covers unassigned code points too)
        if unicodedata.category(ch) == "Cn" and not any(lo <= cp <= hi for lo, hi in textnorm.DECORATING_MARKS):
            continue
        yield cp, ch


def _pages(records: Iterator[tuple[int, str]]) -> list[list[object]]:
    """`[[page start, count, digest], ...]` for the pages that hold at least one record; records come in code point order."""
    out: list[list[object]] = []
    current = -1
    count = 0
    h = _FNV_OFFSET
    for cp, line in records:
        page = cp - cp % PAGE
        if page != current:
            if current >= 0:
                out.append([current, count, _hex(h)])
            current, count, h = page, 0, _FNV_OFFSET
        count += 1
        h = fnv1a32(f"{cp:x}:{line}\n".encode(), h)
    if current >= 0:
        out.append([current, count, _hex(h)])
    return out


def fold_pages(fold: Callable[[str], str]) -> list[list[object]]:
    def changed() -> Iterator[tuple[int, str]]:
        for cp, ch in _code_points():
            folded = fold(ch)
            if folded != ch:
                yield cp, folded

    return _pages(changed())


def class_pages() -> list[list[object]]:
    def classes() -> Iterator[tuple[int, str]]:
        for cp, ch in _code_points():
            first = unicodedata.category(ch)[0]
            if first in "LNM":
                yield cp, first.lower()

    return _pages(classes())


def random_strings(pool: list[int], seed: int, count: int, max_length: int) -> Iterator[str]:
    x = seed & _MASK

    def nxt() -> int:
        nonlocal x
        x ^= (x << 13) & _MASK
        x ^= x >> 17
        x ^= (x << 5) & _MASK
        return x

    for _ in range(count):
        length = 1 + nxt() % max_length
        yield "".join(chr(pool[nxt() % len(pool)]) for _ in range(length))


def random_digest(
    fold: Callable[[str], str], words: Callable[[str], list[str]], pool: list[int], seed: int, count: int, max_length: int
) -> str:
    h = _FNV_OFFSET
    for i, text in enumerate(random_strings(pool, seed, count, max_length)):
        folded = fold(text)
        h = fnv1a32(f"{i}:{folded}|{'/'.join(words(folded))}\n".encode(), h)
    return _hex(h)
