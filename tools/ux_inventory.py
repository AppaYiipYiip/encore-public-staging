"""Builds docs/tasks/UX-REVIEW.md's inventory from the app's code: every control (ListTile, button, switch, icon button, menu entry) per screen file with its
label and what its handler does, and flags: DUP (the same label on more than one screen), NOOP (no handler, or an empty one), MODE (mentions legacy, portal,
fetch service or people service: may only work on one kind of server)."""
import collections
import os
import re

ROOT = r"C:\Users\you\Desktop\encore-workspace\encore\app\lib\features"
CONTROL = re.compile(
    r"(ListTile|SwitchListTile|RadioListTile|CheckboxListTile|FilledButton(?:\.tonal|\.icon)?|OutlinedButton(?:\.icon)?|TextButton(?:\.icon)?|IconButton|"
    r"PopupMenuItem|MenuAction|FloatingActionButton|InkWell|Chip|ActionChip|FilterChip|ChoiceChip|Switch)\(")
LABEL = [
    re.compile(r"title:\s*(?:const\s+)?Text\(\s*(['\"])(.+?)\1"),
    re.compile(r"label:\s*(?:const\s+)?Text\(\s*(['\"])(.+?)\1"),
    re.compile(r"tooltip:\s*(['\"])(.+?)\1"),
    re.compile(r"child:\s*(?:const\s+)?Text\(\s*(['\"])(.+?)\1"),
    re.compile(r"\blabel:\s*(['\"])(.+?)\1"),
    re.compile(r"\btitle:\s*(['\"])(.+?)\1"),
]
MODE = re.compile(r"legacy|portal|fetchService|people service|RequestBackend|requestBackend", re.I)


def balanced(text, start):
    """The text from the '(' at [start] to its matching ')'."""
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:start + 400]


def handler(block):
    for key in ("onTap", "onPressed", "onChanged", "onLongPress", "onSelected"):
        m = re.search(r"\b" + key + r":\s*(null|\(\)\s*(?:async\s*)?(?:=>|\{)([^\n]{0,70})|[\w.]+(?:\([^)]{0,30}\))?)", block)
        if m:
            body = m.group(0)[len(key) + 1:].strip()
            return key, re.sub(r"\s+", " ", body)[:80]
    return None, ""


rows = []
for dirpath, _, files in os.walk(ROOT):
    for name in sorted(files):
        if not name.endswith(".dart"):
            continue
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        text = open(path, encoding="utf-8").read()
        for m in CONTROL.finditer(text):
            block = balanced(text, m.end() - 1)
            label = ""
            for rx in LABEL:
                lm = rx.search(block)
                if lm:
                    label = lm.group(2)
                    break
            key, body = handler(block)
            kind = m.group(1)
            if kind in ("InkWell", "Chip", "Switch") and not label:
                continue
            if not label and not body:
                continue
            flags = []
            if key is None or body in ("null", "() {}", "() { }"):
                flags.append("NOOP?")
            if MODE.search(block):
                flags.append("MODE")
            line = text.count("\n", 0, m.start()) + 1
            rows.append((rel, line, kind, label, key or "-", body, flags))

by_label = collections.defaultdict(set)
for rel, line, kind, label, key, body, flags in rows:
    if label and len(label) > 2:
        by_label[label.lower()].add(rel.split("/")[0] + "/" + rel.split("/")[-1])
dups = {k for k, v in by_label.items() if len(v) > 1}

areas = collections.OrderedDict()
for r in rows:
    areas.setdefault(r[0].split("/")[0], []).append(r)

out = []
out.append("# UX review of the phone app: every control, and the questions asked of each (AUDIT F44, F37)\n")
out.append("Generated from the code on 2026-10-30 by `tools/ux_inventory.py` (the list below), then judged by hand. **It is an inventory, not a walk.** The owner's request: *\"test every single feature and question yourself: should this be like this, should it be here, is it not already here, does it make sense?\"* The advisor judges it in batches; each verdict becomes a fix, a drawing or a decision, and journey J12 of `RELEASE-CANDIDATE.md` walks the same list.\n")
out.append("**Questions asked of every row:** (1) What is it for, and who needs it? (2) Is it already somewhere else (**DUP**)? (3) Is it in the right place? (4) Would somebody who never heard of Navidrome, Tailscale or \"refs\" understand its words? (5) Does it look like what it is (a hint versus typed text, information versus a button; does it look broken)? (6) Does it work in each mode: Encore or plain server (**MODE**), light or dark, offline, an empty server? (7) Does it follow Spotify's conventions (long-press, the ⋯ menu)? (8) Are its empty and error states in plain words?\n")
out.append("**Verdicts (to be filled):** keep, move, merge, remove, reword, fix, needs drawing, P4. **Flags:** `DUP` the same label on more than one screen; `NOOP?` no handler found (a static label, or a control that does nothing: check); `MODE` the code mentions legacy, the request portal, the old fetch service or the old people service: may work on only one kind of server.\n")
out.append("**Batches for the advisor:** 1 Home, Library, Search, catalogue album and artist pages, Now playing and its menu, Settings root, Your server. 2 the settings sub-pages, invitations and people, What's new, Jam, Year in Music, profiles, sign-in, join and first run. 3 the states: offline, server away, empty server, the first minutes after sign-in.\n")
out.append(f"**Counts:** {len(rows)} controls found in {len(areas)} feature folders; {len(dups)} labels appear on more than one screen.\n")
for area, items in areas.items():
    out.append(f"\n## `{area}/` ({len(items)} controls)\n")
    out.append("| File:line | Kind | Label | Handler | Flags | Verdict |\n|-----------|------|-------|---------|-------|---------|")
    for rel, line, kind, label, key, body, flags in items:
        f = list(flags)
        if label and label.lower() in dups:
            f.append("DUP")
        lab = label.replace("|", "\\|").replace("\n", " ")[:70]
        h = (key + " " + body).replace("|", "\\|")[:80] if key != "-" else "-"
        out.append(f"| `{rel}:{line}` | {kind} | {lab} | {h} | {' '.join(f)} | |")
open(r"C:\Users\you\Desktop\encore-workspace\encore\docs\tasks\UX-REVIEW.md", "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
print(len(rows), "controls,", len(areas), "areas,", len(dups), "duplicate labels")
for k in sorted(dups)[:40]:
    print("  DUP:", k, "->", sorted(by_label[k]))
