"""Tests of the local roadmap board's server (tools/roadmap_board.py): what it serves, what it refuses, and that a save is safe. The plan is ONE flat list (D-57)."""
from __future__ import annotations

import http.client
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_board as rb  # noqa: E402
import roadmap_plan as rp  # noqa: E402
import roadmap_testkit as kit  # noqa: E402

HDR = {"X-Roadmap": "1", "Content-Type": "application/json"}
#: P1-03 needs nothing here, so it can move; P1-02 still needs P1-01 (a strict chain has only one valid order, which would leave nothing to drag)
FREE = kit.BASE_TASKS.replace("Needs: P1-02 [i]. Why: it says so.", "Needs: none.")


class BoardTests(unittest.TestCase):
    def start(self, **tree_args) -> None:
        tree_args.setdefault("tasks", FREE)
        self.root = kit.tree(**tree_args)
        self.srv = rb.make_server(self.root, 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()

    def call(self, method: str, path: str, body: object | None = None, headers: dict | None = None, host: str | None = None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        ctype = r.getheader("Content-Type") or ""
        c.close()
        return r.status, (json.loads(data) if ctype.startswith("application/json") else data)

    def token(self) -> str:
        return self.call("GET", "/api/state")[1]["version"]

    def order_file(self) -> str:
        return (self.root / "docs/roadmap/order.json").read_text(encoding="utf-8")

    def test_the_page_and_the_state_are_served(self) -> None:
        self.start()
        code, page = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"Encore roadmap", page)
        code, st = self.call("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertEqual(len(st["version"]), 16)          # a content hash, not a counter
        self.assertEqual(st["order"], ["P1-01", "P1-02", "P1-03"])
        self.assertNotIn("milestones", st)                  # no phases, no groups
        self.assertNotIn("segments", st)
        self.assertEqual(st["counts"], {"done": 0, "built": 0, "reopened": 0, "left": 3, "all": 3, "later": 0})
        self.assertEqual(st["items"]["P1-02"]["needs"][0]["id"], "P1-01")
        self.assertEqual(st["items"]["P1-03"]["days"], 7)

    def test_a_query_string_on_the_page_address_is_ignored(self) -> None:
        self.start()
        self.assertEqual(self.call("GET", "/?v=2")[0], 200)
        self.assertEqual(self.call("GET", "/api/state?x=1")[0], 200)

    def test_a_request_for_another_host_is_refused(self) -> None:
        self.start()
        self.assertEqual(self.call("GET", "/api/state", host="evil.example")[0], 403)
        self.assertEqual(self.call("POST", "/api/order", {"version": "x", "order": kit.GOOD_ORDER}, HDR, host="evil.example")[0], 403)

    def test_a_save_without_the_custom_header_is_refused(self) -> None:
        self.start()
        code, _ = self.call("POST", "/api/order", {"version": self.token(), "order": kit.GOOD_ORDER}, {"Content-Type": "application/json"})
        self.assertEqual(code, 403)

    def test_an_illegal_drop_is_refused_and_the_file_is_untouched(self) -> None:
        self.start()
        before = self.order_file()
        code, body = self.call("POST", "/api/order", {"version": self.token(), "order": ["P1-02", "P1-01", "P1-03"]}, HDR)
        self.assertEqual(code, 400)
        self.assertIn("comes before P1-01", body["error"])
        self.assertEqual(self.order_file(), before)

    def test_a_good_drop_is_saved_and_shown(self) -> None:
        self.start()
        tok = self.token()
        good = ["P1-03", "P1-01", "P1-02"]
        code, body = self.call("POST", "/api/order", {"version": tok, "order": good}, HDR)
        self.assertEqual(code, 200)
        self.assertNotEqual(body["version"], tok)
        st = self.call("GET", "/api/state")[1]
        self.assertEqual(st["order"], good)
        self.assertEqual(st["version"], body["version"])
        lines = self.order_file().splitlines()
        self.assertEqual(sum(1 for line in lines if line.strip().startswith('"P1-')), 3)   # one entry per line: a readable diff

    def test_a_save_from_an_old_page_conflicts_and_loses_nothing(self) -> None:
        self.start()
        old = self.token()
        first = ["P1-01", "P1-03", "P1-02"]
        self.assertEqual(self.call("POST", "/api/order", {"version": old, "order": first}, HDR)[0], 200)
        code, body = self.call("POST", "/api/order", {"version": old, "order": kit.GOOD_ORDER}, HDR)
        self.assertEqual(code, 409)
        self.assertIn("changed", body["error"])
        self.assertEqual(self.call("GET", "/api/state")[1]["order"], first)

    def test_a_change_of_the_file_underneath_makes_the_open_page_stale(self) -> None:
        self.start()
        tok = self.token()
        path = self.root / "docs/roadmap/order.json"
        path.write_text(path.read_text(encoding="utf-8").replace('"P1-03"', '"P1-03"\n'), encoding="utf-8")   # an agent edits the file
        self.assertEqual(self.call("POST", "/api/order", {"version": tok, "order": kit.GOOD_ORDER}, HDR)[0], 409)

    def test_an_entry_that_is_not_an_item_id_is_refused(self) -> None:
        self.start()
        for bad in ([{"milestone": "M0"}, "P1-01", "P1-02", "P1-03"], ["P1-01", "P1-02", 7], "P1-01"):
            code, body = self.call("POST", "/api/order", {"version": self.token(), "order": bad}, HDR)
            self.assertEqual(code, 400, bad)

    def test_a_proposal_can_be_added_to_the_list_and_taken_out_again(self) -> None:
        items = dict(kit.ITEMS)
        items["N-01"] = {"title": "Share links", "kind": "feature", "proposal": True, "size": "M", "needs": []}
        self.start(items=items, proposed="| N-01 | x |\n")
        # a proposal always sits in Now or Later (no waiting box): the test places it in Later, then moves it to Now and back
        rp.write_order(self.root, kit.GOOD_ORDER, ["N-01"])
        self.assertEqual(self.call("GET", "/api/state")[1]["later"], ["N-01"])
        code, _ = self.call("POST", "/api/move", {"version": self.token(), "item": "N-01", "to": "now"}, HDR)
        self.assertEqual(code, 200)
        self.assertEqual(self.call("GET", "/api/state")[1]["order"], kit.GOOD_ORDER + ["N-01"])
        code, _ = self.call("POST", "/api/move", {"version": self.token(), "item": "N-01", "to": "later"}, HDR)
        self.assertEqual(code, 200)
        self.assertEqual(self.call("GET", "/api/state")[1]["later"], ["N-01"])

    def test_the_real_plan_of_the_repository_loads_and_has_no_errors(self) -> None:
        st = rb.board_state(rp.ROOT)
        self.assertEqual(st["errors"], [])
        self.assertGreater(len(st["items"]), 90)
        self.assertTrue(all(isinstance(e, str) for e in st["order"]), "the real order.json is one flat list of ids")


if __name__ == "__main__":
    unittest.main()
