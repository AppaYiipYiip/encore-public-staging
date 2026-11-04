"""Tests of the roadmap notes (tools/roadmap_notes.py): the shared conversation between the owner, the agents and the developers."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_notes as rn  # noqa: E402

T0 = datetime(2026, 11, 4, 18, 0, 0, tzinfo=timezone.utc)
KNOWN = {"P3-12", "P2-22", "N-04"}


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


class NotesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def add(self, item="P3-12", role="owner", body="hello", minutes=0, **kw) -> dict:
        return rn.add(self.root, item, role, kw.pop("by", "Owner"), body, when=at(minutes), known_items=KNOWN, **kw)

    def test_a_note_is_its_own_file_in_the_folder_of_its_item(self) -> None:
        n = self.add(body="Please make the first friend wait until the key exists.")
        f = self.root / rn.NOTES / "P3-12" / f"{n['id']}.json"
        self.assertTrue(f.exists())
        self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["body"], n["body"])
        self.assertRegex(n["id"], r"^20261104T180000Z-owner-[0-9a-f]{4}$")
        notes, problems = rn.read_all(self.root)
        self.assertEqual((len(notes), problems), (1, []))

    def test_two_notes_in_the_same_second_never_share_a_file(self) -> None:
        a = self.add(body="one")
        b = self.add(role="dev", by="Sam", body="two")
        c = self.add(body="three")
        self.assertEqual(len({a["id"], b["id"], c["id"]}), 3)
        self.assertEqual(len(rn.read_all(self.root)[0]), 3)

    def test_what_looks_like_a_secret_is_refused_and_nothing_is_written(self) -> None:
        for text in ("-----BEGIN OPENSSH PRIVATE KEY-----\nabc", "token ghp_" + "a" * 36, "AKIA" + "A" * 16,
                     "https://login.tailscale.com/a/0123456789ab", "see https://x.example/p?token=" + "z" * 24, "password: hunter22hunter22"):
            with self.assertRaises(rn.NoteError, msg=text):
                self.add(body=text)
        self.assertFalse((self.root / rn.NOTES).exists() and any((self.root / rn.NOTES).glob("*/*.json")))

    def test_an_ordinary_sentence_about_tokens_and_keys_is_not_refused(self) -> None:
        for text in ("The conflict token is a hash of the file.", "Where does the release key live? In the password manager.", "password reset is P3-16"):
            self.add(body=text)

    def test_bad_input_is_refused_in_plain_words(self) -> None:
        for kw, word in (({"item": "P9-99"}, "not an item of the plan"), ({"item": "../x"}, "must be a task id"), ({"role": "boss"}, "role"),
                         ({"body": "  "}, "empty"), ({"body": "x" * 4001}, "too long"), ({"by": ""}, "who is writing"), ({"type": "idea"}, "type")):
            with self.assertRaises(rn.NoteError) as cm:
                self.add(**kw)
            self.assertIn(word, str(cm.exception))

    def test_the_general_thread_needs_no_item(self) -> None:
        self.add(item=rn.BOARD, body="Anything not tied to one item.")
        self.assertEqual(len(rn.thread(rn.read_all(self.root)[0], rn.BOARD)), 1)

    def test_an_edit_replaces_the_text_and_a_retraction_removes_it(self) -> None:
        a = self.add(body="first draft")
        b = self.add(body="second draft", minutes=1, replaces=a["id"])
        view = rn.thread(rn.read_all(self.root)[0], "P3-12")
        self.assertEqual([n["body"] for n in view], ["second draft"])
        self.assertTrue(view[0]["edited"])
        self.add(body="", minutes=2, replaces=b["id"])
        self.assertEqual(rn.thread(rn.read_all(self.root)[0], "P3-12"), [])
        self.assertEqual(len(list((self.root / rn.NOTES / "P3-12").glob("*.json"))), 3)       # nothing was deleted

    def test_a_reply_or_a_replacement_must_point_at_a_note_of_the_same_item(self) -> None:
        a = self.add(item="P2-22", body="x")
        with self.assertRaises(rn.NoteError):
            self.add(item="P3-12", body="y", reply_to=a["id"])
        with self.assertRaises(rn.NoteError):
            self.add(item="P3-12", body="y", replaces="20200101T000000Z-owner-0000")

    def test_waiting_is_derived_and_stops_when_the_asked_role_writes_on_the_item(self) -> None:
        self.add(role="agent", by="Claude", body="Which store do you want first?", to=["owner"], minutes=0)
        self.add(item="N-04", role="agent", by="Claude", body="Something for the dev.", to=["dev"], minutes=1)
        notes = rn.read_all(self.root)[0]
        self.assertEqual([n["item"] for n in rn.inbox(notes, "owner")], ["P3-12"])
        self.assertEqual(rn.summary(notes)["P3-12"]["waiting"], ["owner"])
        self.add(role="owner", body="The Play Store first.", minutes=5)
        notes = rn.read_all(self.root)[0]
        self.assertEqual(rn.inbox(notes, "owner"), [])
        self.assertEqual([n["item"] for n in rn.inbox(notes, "dev")], ["N-04"])             # another item's question still waits
        self.assertEqual(rn.summary(notes)["P3-12"]["waiting"], [])

    def test_a_note_addressed_to_oneself_does_not_wait(self) -> None:
        self.add(role="owner", body="Reminder to me.", to=["owner"])
        self.assertEqual(rn.inbox(rn.read_all(self.root)[0], "owner"), [])

    def test_details_are_counted_apart(self) -> None:
        self.add(body="The icon must work on a dark launcher.", type="detail")
        self.add(body="ok", minutes=1)
        s = rn.summary(rn.read_all(self.root)[0])["P3-12"]
        self.assertEqual((s["count"], s["details"]), (2, 1))

    def test_ci_finds_a_misnamed_unknown_or_dangling_file_and_only_warns_about_an_orphan(self) -> None:
        n = self.add(body="fine")
        d = self.root / rn.NOTES / "P3-12"
        good = json.loads((d / f"{n['id']}.json").read_text(encoding="utf-8"))
        (d / "20261104T180100Z-owner-aaaa.json").write_text(json.dumps({**good, "id": "20261104T180100Z-owner-bbbb"}), encoding="utf-8")        # name != id
        (d / "20261104T180200Z-owner-cccc.json").write_text(json.dumps({**good, "id": "20261104T180200Z-owner-cccc", "mood": "x"}), encoding="utf-8")  # unknown field
        (d / "20261104T180300Z-owner-dddd.json").write_text(json.dumps({**good, "id": "20261104T180300Z-owner-dddd", "replaces": "20200101T000000Z-owner-0000"}), encoding="utf-8")
        (d / "broken.json").write_text("{not json", encoding="utf-8")
        (self.root / rn.NOTES / "loose.json").write_text("{}", encoding="utf-8")
        errs, _ = rn.validate_files(self.root, KNOWN)
        text = "\n".join(errs)
        for word in ("must equal the file name", "unknown field", "does not exist", "not readable JSON", "docs/roadmap/notes/<ITEM>/<id>.json"):
            self.assertIn(word, text)
        # an item that left the plan is history, not a failure
        errs2, warns = rn.validate_files(self.root, set())
        self.assertTrue(any("not an item of the plan any more" in w for w in warns))

    def test_a_secret_that_got_into_a_file_by_hand_fails_ci(self) -> None:
        n = self.add(body="fine")
        f = self.root / rn.NOTES / "P3-12" / f"{n['id']}.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        d["body"] = "key ghp_" + "b" * 36
        f.write_text(json.dumps(d), encoding="utf-8")
        errs, _ = rn.validate_files(self.root, KNOWN)
        self.assertTrue(any("GitHub token" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
