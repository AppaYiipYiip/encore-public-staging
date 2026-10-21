"""The Suggestions page (docs/47): on or off, when it last ran, how many people have lists. Never what a list holds."""
import unittest

from tests.test_site import SiteTestBase


class TheSuggestionsPageTest(SiteTestBase):
    def setUp(self):
        super().setUp()
        self.key = self.sign_in()

    def get(self):
        return self.call("GET", "/admin/api/recs", cookie=self.key)

    def test_a_server_without_suggestions_is_told_so_not_given_an_error(self):
        del self.docker.stack_containers["encore-recs"]
        r, data = self.get()
        self.assertEqual((r.status, data), (200, {"installed": False}))
        self.assertEqual(self.stack.recs_calls, [])

    def test_the_owners_view_comes_from_the_service_asked_as_the_owner(self):
        r, data = self.get()
        self.assertEqual((r.status, data["enabled"], data["peopleWithLists"]), (200, True, 2))
        self.assertEqual(self.stack.recs_calls[-1][:2], ("GET", ""))
        self.assertEqual(self.stack.recs_calls[-1][2]["u"], "dana")

    def test_the_page_needs_a_signed_in_owner(self):
        self.assertEqual(self.call("GET", "/admin/api/recs")[0].status, 401)
        self.assertEqual(self.call("PUT", "/admin/api/recs/settings", {"enabled": False})[0].status, 401)

    def test_switching_suggestions_off_is_passed_on_with_only_that_choice(self):
        r, _ = self.call("PUT", "/admin/api/recs/settings", {"enabled": False, "sneaky": 1}, cookie=self.key)
        self.assertEqual(r.status, 200)
        self.assertEqual(self.stack.recs_calls[-1][:2] + (self.stack.recs_calls[-1][3],), ("PUT", "/settings", {"enabled": False}))

    def test_the_services_own_refusal_reaches_the_owner(self):
        self.stack.recs_replies[("PUT", "/settings")] = (400, {"error": "Suggestions are on or off."})
        r, data = self.call("PUT", "/admin/api/recs/settings", {"enabled": "maybe"}, cookie=self.key)
        self.assertEqual((r.status, data["error"]), (400, "Suggestions are on or off."))

    def test_make_everybodys_lists_now(self):
        self.stack.recs_replies[("POST", "/rebuild")] = (202, {"running": True})
        r, data = self.call("POST", "/admin/api/recs/rebuild", {}, cookie=self.key)
        self.assertEqual((r.status, data), (202, {"running": True}))

    def test_when_the_service_is_there_but_does_not_answer_the_owner_is_told_to_try_again(self):
        self.stack.recs_up = False
        r, data = self.get()
        self.assertEqual((r.status, data["error"]), (502, "unreachable"))
        self.assertIn("suggestions service did not answer", data["message"])

    def test_wrong_methods_and_unknown_paths(self):
        self.assertEqual(self.call("POST", "/admin/api/recs", {}, cookie=self.key)[0].status, 405)
        self.assertEqual(self.call("GET", "/admin/api/recs/settings", cookie=self.key)[0].status, 405)
        self.assertEqual(self.call("GET", "/admin/api/recs/rebuild", cookie=self.key)[0].status, 405)
        self.assertEqual(self.call("GET", "/admin/api/recs/lists", cookie=self.key)[0].status, 404)

    def test_the_page_has_no_route_that_could_show_somebodys_list(self):
        for path in ("/admin/api/recs/home", "/admin/api/recs/people", "/admin/api/recs/lists/sam", "/admin/api/recs/seeds"):
            self.assertEqual(self.call("GET", path, cookie=self.key)[0].status, 404, path)


class OnTheFrontPageTest(SiteTestBase):
    def test_suggestions_are_a_part_that_works_or_is_not_switched_on(self):
        key = self.sign_in()
        parts = {p["key"]: p for p in self.call("GET", "/admin/api/today", cookie=key)[1]["parts"]}
        self.assertEqual(parts["recs"]["state"], "working")
        del self.docker.stack_containers["encore-recs"]
        self.stack.recs_up = False
        parts = {p["key"]: p for p in self.call("GET", "/admin/api/today", cookie=key)[1]["parts"]}
        self.assertEqual((parts["recs"]["state"], parts["recs"]["note"]), ("off", "Not switched on."))


if __name__ == "__main__":
    unittest.main()
