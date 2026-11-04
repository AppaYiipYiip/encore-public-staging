"""Tests of the board's shared-memory side: notes, ideas, "Working now", the security of showing other people's text, and one board at a time."""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_board as rb  # noqa: E402
import roadmap_launch as launch  # noqa: E402
import roadmap_notes as rn  # noqa: E402
import roadmap_testkit as kit  # noqa: E402

HDR = {"X-Roadmap": "1", "Content-Type": "application/json"}


class Base(unittest.TestCase):
    def start(self, **tree_args) -> None:
        self.root = kit.tree(**tree_args)
        self.srv = rb.make_server(self.root, 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()

    def call(self, method, path, body=None, headers=None, host=None, raw=False):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        hdrs = dict(r.getheaders())
        c.close()
        if raw:
            return r.status, data, hdrs
        return r.status, (json.loads(data) if (r.getheader("Content-Type") or "").startswith("application/json") else data)

    def post(self, path, body, headers=HDR):
        return self.call("POST", path, body, headers)

    def state(self) -> dict:
        return self.call("GET", "/api/state")[1]


class SecurityTests(Base):
    def test_the_page_is_served_with_a_policy_that_allows_only_its_own_script_and_style(self) -> None:
        self.start()
        code, body, h = self.call("GET", "/", raw=True)
        self.assertEqual(code, 200)
        csp = h["Content-Security-Policy"]
        text = body.decode("utf-8")
        for tag, directive in (("script", "script-src"), ("style", "style-src")):
            blocks = re.findall(rf"<{tag}>(.*?)</{tag}>", text, re.S)
            self.assertGreaterEqual(len(blocks), 1)
            for b in blocks:
                want = "'sha256-" + base64.b64encode(hashlib.sha256(b.encode("utf-8")).digest()).decode() + "'"
                self.assertIn(want, csp.split(directive)[1].split(";")[0])
        for must in ("default-src 'none'", "connect-src 'self'", "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'"):
            self.assertIn(must, csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertEqual((h["X-Frame-Options"], h["Referrer-Policy"], h["X-Content-Type-Options"]), ("DENY", "no-referrer", "nosniff"))

    def test_the_page_never_puts_text_into_the_page_as_html(self) -> None:
        text = rb.PAGE.read_text(encoding="utf-8")
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setTimeout(\"", "javascript:"):
            self.assertNotIn(bad, text, bad)
        self.assertIsNone(re.search(r"\son[a-z]+\s*=", re.sub(r"<script>.*?</script>", "", text, flags=re.S)), "an inline event handler would be blocked by the policy")
        self.assertIsNone(re.search(r'<[^>]+\sstyle\s*=', text), "a style attribute would be blocked by the policy")
        self.assertNotRegex(text, r"(?:src|href)=\"https?://")          # nothing is loaded from outside

    def test_the_names_and_ports_this_board_answers_to(self) -> None:
        self.start()
        self.assertEqual(self.call("GET", "/api/hello", host=f"roadmap.localhost:{self.port}")[0], 200)
        self.assertEqual(self.call("GET", "/api/hello", host=f"localhost:{self.port}")[0], 200)
        self.assertEqual(self.call("GET", "/api/hello", host=f"roadmap.localhost:{self.port + 1}")[0], 403)      # a different port is not this board
        self.assertEqual(self.call("GET", "/api/hello", host="roadmap.localhost")[0], 403)                        # no port means port 80
        self.assertEqual(self.call("GET", "/api/hello", host=f"evil.example:{self.port}")[0], 403)
        self.assertEqual(self.call("POST", "/api/notes", {"item": "P1-01"}, HDR, host="evil.example")[0], 403)

    def test_every_write_needs_the_custom_header_and_an_object(self) -> None:
        self.start()
        for path in ("/api/notes", "/api/ideas", "/api/order"):
            self.assertEqual(self.call("POST", path, {}, {"Content-Type": "application/json"})[0], 403, path)
        self.assertEqual(self.call("POST", "/api/notes", None, HDR)[0], 400)           # an empty body is not an object with a role
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", "/api/notes", body="[1,2]", headers={"Host": f"127.0.0.1:{self.port}", **HDR})
        self.assertEqual(c.getresponse().status, 400)
        c.close()

    def test_a_note_with_markup_is_stored_and_sent_as_inert_text(self) -> None:
        self.start()
        evil = "<img src=x onerror=alert(1)> <script>alert(2)</script>"
        code, _ = self.post("/api/notes", {"item": "P1-01", "role": "owner", "by": "Owner", "body": evil})
        self.assertEqual(code, 200)
        code, got, h = self.call("GET", "/api/notes?item=P1-01", raw=True)
        self.assertTrue(h["Content-Type"].startswith("application/json"))
        self.assertEqual(json.loads(got)["notes"][0]["body"], evil)


class NotesApiTests(Base):
    def test_a_note_written_on_the_page_is_a_file_shows_in_the_list_and_waits_for_the_asked_role(self) -> None:
        self.start()
        s0 = self.state()["stamp"]
        code, body = self.post("/api/notes", {"item": "P1-02", "role": "owner", "by": "Owner", "body": "Please keep it small.", "to": ["agent"], "type": "detail"})
        self.assertEqual(code, 200)
        f = self.root / rn.NOTES / "P1-02" / f"{body['note']['id']}.json"
        self.assertTrue(f.exists())
        st = self.state()
        self.assertEqual(st["items"]["P1-02"]["notes"], {"count": 1, "details": 1, "waiting": ["agent"], "last": body["note"]["at"]})
        self.assertNotEqual(st["stamp"], s0)                                           # the open page notices the change
        got = self.call("GET", "/api/notes?item=P1-02")[1]
        self.assertEqual([(n["body"], n["waiting_for"]) for n in got["notes"]], [("Please keep it small.", ["agent"])])

    def test_the_page_writes_only_as_the_owner_and_never_a_secret(self) -> None:
        self.start()
        for payload, word in (({"role": "agent", "by": "Claude", "item": "P1-01", "body": "hi"}, "writes only as the owner"),
                              ({"role": "dev", "by": "Sam", "item": "P1-01", "body": "hi"}, "writes only as the owner"),
                              ({"item": "P1-01", "body": "hi"}, "writes only as the owner"),
                              ({"role": "owner", "by": "O", "item": "P9-99", "body": "hi"}, "not an item"),
                              ({"role": "owner", "by": "O", "item": "P1-01", "body": "https://login.tailscale.com/a/0123456789ab"}, "Tailscale"),
                              ({"role": "owner", "by": "O", "item": "P1-01", "body": ["x"]}, "must be text")):
            code, body = self.post("/api/notes", payload)
            self.assertEqual(code, 400, payload)
            self.assertIn(word, body["error"])
        self.assertFalse(any((self.root / rn.NOTES).glob("*/*.json")) if (self.root / rn.NOTES).exists() else False)

    def test_the_general_thread_has_its_own_summary_and_a_bad_item_is_refused(self) -> None:
        self.start()
        self.post("/api/notes", {"item": rn.BOARD, "role": "owner", "by": "Owner", "body": "A general question."})
        self.assertEqual(self.state()["board_thread"]["count"], 1)
        self.assertEqual(self.call("GET", "/api/notes?item=../etc")[0], 400)
        self.assertEqual(self.call("GET", "/api/notes")[0], 400)

    def test_a_broken_note_file_is_reported_not_fatal(self) -> None:
        self.start()
        self.post("/api/notes", {"item": "P1-01", "role": "owner", "by": "Owner", "body": "fine"})
        (self.root / rn.NOTES / "P1-01" / "junk.json").write_text("{nope", encoding="utf-8")
        st = self.state()
        self.assertEqual(st["items"]["P1-01"]["notes"]["count"], 1)
        self.assertTrue(any("junk.json" in p for p in st["note_problems"]))


class IdeasAndWorkTests(Base):
    def test_an_idea_typed_on_the_page_goes_straight_into_the_list_at_the_end_or_the_top(self) -> None:
        self.start()
        code, body = self.post("/api/ideas", {"role": "owner", "by": "Owner", "title": "A better logo", "note": "Dark launcher friendly.", "kind": "design", "size": "S"})
        self.assertEqual((code, body["idea"]["id"], body["idea"]["position"]), (200, "N-01", "end"))
        st = self.state()
        self.assertEqual(st["order"], ["P1-01", "P1-02", "P1-03", "N-01"])          # his own idea is his yes: no second list to accept it from
        self.assertTrue(st["items"]["N-01"]["proposal"] and st["items"]["N-01"]["pending"])
        self.assertEqual((st["items"]["N-01"]["from"], st["errors"]), ("Owner", []))
        code, body = self.post("/api/ideas", {"role": "owner", "by": "Owner", "title": "Sleep timer", "kind": "feature", "size": "M", "position": "top"})
        self.assertEqual((code, body["idea"]["id"]), (200, "N-02"))
        self.assertEqual(self.state()["order"][0], "N-02")
        for bad in ({"title": "", "kind": "design", "size": "S"}, {"title": "x", "kind": "design", "size": "S", "position": "middle"}):
            self.assertEqual(self.post("/api/ideas", {"role": "owner", "by": "Owner", **bad})[0], 400)

    def test_working_now_shows_the_claims_agents_announced_and_the_page_cannot_announce(self) -> None:
        self.start()
        self.assertEqual(self.post("/api/work", {"action": "start", "role": "owner", "by": "Owner", "items": ["P1-02"], "doing": "x"})[0], 404)   # no such endpoint any more
        rw = __import__("roadmap_work")
        rw.start(self.root, "agent", "Claude (Sonnet 5.5)", ["P1-02"], "the second thing", "tests exist", known_items={"P1-02"}, wdir=self.srv.wdir)
        w = self.state()["working"]
        self.assertEqual(set(w), {"claims", "staleHours"})                         # claims only: no pull requests, no GitHub
        self.assertEqual([(c["by"], c["items"], c["status"], c["maybe_stopped"]) for c in w["claims"]], [("Claude (Sonnet 5.5)", ["P1-02"], "active", False)])


class CheckApiTests(Base):
    """The owner's three buttons. He is not the tester and "built, not walked" is the word until proven, so his tick never proves an engineering item."""
    ITEMS = {"P1-01": {"title": "A", "kind": "owner"}, "P1-02": {"title": "B", "kind": "feature", "judge": True}, "P1-03": {"title": "C", "kind": "feature"}}
    FREE = kit.BASE_TASKS.replace("Needs: P1-02 [i]. Why: it says so.", "Needs: none.")

    def begin(self, **kw) -> None:
        kw.setdefault("tasks", self.FREE)
        kw.setdefault("items", self.ITEMS)
        self.start(**kw)

    def check(self, item, action, body="", role="owner"):
        return self.post("/api/check", {"role": role, "item": item, "action": action, "body": body})

    def test_i_did_this_finishes_an_item_only_he_can_finish_and_shows_as_done_with_his_word(self) -> None:
        self.begin()
        s0 = self.state()
        self.assertTrue(s0["items"]["P1-01"]["can_finish"] and not s0["items"]["P1-03"]["can_finish"])
        code, body = self.check("P1-01", "finish", "Protected main.")
        self.assertEqual((code, body["state"]), (200, "walked"))
        st = self.state()
        self.assertEqual((st["items"]["P1-01"]["state"], "P1-01" in st["order"], st["errors"]), ("walked", False, []))
        self.assertIn("Protected main.", st["items"]["P1-01"]["evidence"])
        self.assertEqual((st["counts"]["done"], st["items"]["P1-01"]["can_finish"]), (1, False))
        self.assertNotEqual(st["stamp"], s0["stamp"])
        code, _ = self.check("P1-01", "uncheck")
        self.assertEqual(code, 200)
        st = self.state()
        self.assertEqual((st["items"]["P1-01"]["state"], st["order"][0]), ("todo", "P1-01"))

    def test_a_judge_check_records_and_does_not_prove(self) -> None:
        self.begin()
        self.assertTrue(self.state()["items"]["P1-02"]["can_judge"])
        self.assertEqual(self.check("P1-02", "judge", "Home knew me.")[0], 200)
        it = self.state()["items"]["P1-02"]
        self.assertEqual((it["state"], it["owner_check"]["body"]), ("todo", "Home knew me."))

    def test_it_does_not_work_reopens_a_built_item_and_waits_for_claude(self) -> None:
        self.begin(status={"P1-03": {"state": "built", "evidence": "built"}})
        code, body = self.check("P1-03", "problem", "Stops at 40 percent.")
        self.assertEqual((code, body["state"]), (200, "reopened"))
        st = self.state()
        self.assertEqual((st["items"]["P1-03"]["state"], st["order"][0], st["items"]["P1-03"]["problem"]["body"]), ("reopened", "P1-03", "Stops at 40 percent."))
        self.assertEqual(st["items"]["P1-03"]["notes"]["waiting"], ["agent"])
        self.assertEqual((st["counts"]["reopened"], st["errors"]), (1, []))

    def test_the_buttons_refuse_what_his_own_rules_do_not_allow(self) -> None:
        self.begin()
        for args, word in ((("P1-03", "finish"), "Claude proves it"), (("P1-03", "judge"), "not one whose acceptance"), (("P1-03", "problem", "x"), "nothing is built yet"),
                           (("P1-03", "dance"), "the action is one of"), (("P9-99", "finish"), "not an item"), (("P1-01", "uncheck"), "nothing to take back")):
            code, body = self.check(*args)
            self.assertEqual(code, 400, args)
            self.assertIn(word, body["error"])
        for role in ("dev", "agent"):
            code, body = self.check("P1-01", "finish", role=role)
            self.assertEqual(code, 400)
            self.assertIn("writes only as the owner", body["error"])
        self.assertEqual(self.call("POST", "/api/check", {"item": "P1-01", "action": "finish"}, {"Content-Type": "application/json"})[0], 403)    # no custom header


class StateAndStaleTests(Base):
    def test_hello_says_which_code_and_folder_and_a_changed_file_makes_the_board_stale(self) -> None:
        self.start()
        hello = self.call("GET", "/api/hello")[1]
        self.assertEqual((hello["board"], hello["code"], hello["root"]), ("encore-roadmap", rb.RUNNING_CODE, str(self.root)))
        self.assertFalse(self.state()["stale"])
        real = rb.RUNNING_CODE
        rb.RUNNING_CODE = "0000000000000000"                  # as if the files had changed after this process started
        try:
            self.assertTrue(self.state()["stale"])
        finally:
            rb.RUNNING_CODE = real

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_uncommitted_changes_under_docs_roadmap_are_reported(self) -> None:
        self.start()
        run = lambda *a: subprocess.run(["git", *a], cwd=self.root, check=True, capture_output=True, text=True)  # noqa: E731
        self.assertIsNone(self.state()["pending"])                               # not a git repository: unknown, not "none"
        run("init", "-q")
        run("add", "-A")
        run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
        self.assertEqual(self.state()["pending"], [])
        self.post("/api/notes", {"item": "P1-01", "role": "owner", "by": "Owner", "body": "hello"})
        p = self.state()["pending"]
        self.assertEqual(len(p), 1)
        self.assertIn("docs/roadmap/notes/P1-01/", p[0])

    def test_the_real_plan_state_has_every_new_field(self) -> None:
        st = rb.board_state(rb.rp.ROOT)
        for k in ("board", "code", "stale", "root", "branch", "pending", "stamp", "board_thread", "working", "note_problems"):
            self.assertIn(k, st)
        self.assertEqual(st["errors"], [])


class LaunchTests(unittest.TestCase):
    def test_the_owners_browser_first_then_brave_chrome_edge_on_windows(self) -> None:
        env = {"ROADMAP_BROWSER": r"D:\mine\browser.exe", "ProgramFiles": r"C:\PF", "ProgramFiles(x86)": r"C:\PF86", "LocalAppData": r"C:\LA"}
        c = [str(x) for x in launch.candidates(env, "win32")]
        self.assertEqual(c[0], r"D:\mine\browser.exe")
        self.assertLess(next(i for i, x in enumerate(c) if "brave.exe" in x), next(i for i, x in enumerate(c) if "chrome.exe" in x))
        self.assertLess(next(i for i, x in enumerate(c) if "chrome.exe" in x), next(i for i, x in enumerate(c) if "msedge.exe" in x))

    def test_an_app_window_when_a_chromium_browser_exists_else_a_plain_tab(self) -> None:
        env = {"ProgramFiles": r"C:\PF", "ProgramFiles(x86)": "", "LocalAppData": ""}
        spawned, tabs = [], []
        what = launch.open_board(8765, True, env, "win32", exists=lambda p: "brave.exe" in str(p), spawn=lambda cmd, **k: spawned.append(cmd), tab=tabs.append)
        self.assertEqual(what, "app window (brave.exe)")
        self.assertEqual(spawned[0][1], "--app=http://roadmap.localhost:8765/")
        self.assertEqual(tabs, [])
        what = launch.open_board(8765, True, env, "win32", exists=lambda p: False, spawn=lambda cmd, **k: spawned.append(cmd), tab=tabs.append)
        self.assertEqual((what, tabs), ("browser tab", ["http://127.0.0.1:8765/"]))
        tabs.clear()
        self.assertEqual(launch.open_board(8765, False, env, "win32", exists=lambda p: True, spawn=lambda *a, **k: 1 / 0, tab=tabs.append), "browser tab")     # --tab asked for
        def broken(*a, **k):
            raise OSError("cannot start")
        self.assertEqual(launch.open_board(8765, True, env, "win32", exists=lambda p: True, spawn=broken, tab=tabs.append), "browser tab")                      # falls back

    def test_a_second_start_opens_the_running_board_but_never_starts_another(self) -> None:
        root = kit.tree()
        srv = rb.make_server(root, 0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            other = launch.probe(port)
            self.assertEqual(other["board"], "encore-roadmap")
            self.assertEqual(launch.decide_when_port_is_taken(other, str(root), rb.RUNNING_CODE, port)[0], "open")
            verdict, msg = launch.decide_when_port_is_taken(other, str(root), "different-code", port)
            self.assertEqual(verdict, "refuse")
            self.assertIn("OLD code", msg)
            self.assertIn("Close the window", msg)
            verdict, msg = launch.decide_when_port_is_taken(other, str(root) + "-other", rb.RUNNING_CODE, port)
            self.assertEqual(verdict, "refuse")
            self.assertIn("another folder", msg)
            with self.assertRaises(OSError):                                       # the same port cannot be bound twice: no silent second server
                rb.make_server(root, port)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertIsNone(launch.probe(port, timeout=0.5))                         # free again
        verdict, msg = launch.decide_when_port_is_taken(None, str(root), "c", port)
        self.assertEqual(verdict, "refuse")
        self.assertIn("another program", msg)

    def test_another_program_on_the_port_is_not_mistaken_for_a_board(self) -> None:
        import socketserver
        from http.server import BaseHTTPRequestHandler

        class Other(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"hello": 1}')

            def log_message(self, *a):
                pass
        s = socketserver.TCPServer(("127.0.0.1", 0), Other)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            self.assertIsNone(launch.probe(s.server_address[1]))
        finally:
            s.shutdown()
            s.server_close()


if __name__ == "__main__":
    unittest.main()
