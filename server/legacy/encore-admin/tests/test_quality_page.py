"""The Music quality page (docs/46, docs/49 P4): the owner switches Soulseek on, sees whether the parts work, and what could not be upgraded."""
import unittest

from tests.test_site import SiteTestBase


class TheQualityPageTest(SiteTestBase):
    def setUp(self):
        super().setUp()
        self.key = self.sign_in()

    def get(self, path="/admin/api/quality"):
        return self.call("GET", path, cookie=self.key)

    def test_a_server_without_the_quality_tier_is_told_so_not_given_an_error(self):
        del self.docker.stack_containers["encore-quality"]
        r, data = self.get()
        self.assertEqual((r.status, data), (200, {"installed": False}))
        self.assertEqual(self.stack.quality_calls, [], "nothing is asked of a service that is not there")

    def test_the_owners_view_comes_from_the_quality_service_asked_as_the_owner(self):
        r, data = self.get()
        self.assertEqual(r.status, 200)
        self.assertEqual(data["settings"], {"soulseek": False, "dailyCap": 40, "minFreeGb": 5.0})
        method, rest, query, body = self.stack.quality_calls[-1]
        self.assertEqual((method, rest, query["u"]), ("GET", "", "dana"))
        self.assertNotIn("correct horse", str(query), "no password, only the music login's token form")

    def test_the_page_needs_a_signed_in_owner(self):
        self.assertEqual(self.call("GET", "/admin/api/quality")[0].status, 401)
        self.assertEqual(self.call("PUT", "/admin/api/quality/settings", {"soulseek": True})[0].status, 401)

    def test_switching_soulseek_on_is_passed_on_and_only_the_known_choices_are(self):
        r, data = self.call("PUT", "/admin/api/quality/settings", {"soulseek": True, "dailyCap": 25, "sneaky": "x", "minFreeGb": 9}, cookie=self.key)
        self.assertEqual(r.status, 200)
        method, rest, query, body = self.stack.quality_calls[-1]
        self.assertEqual((method, rest, body), ("PUT", "/settings", {"soulseek": True, "dailyCap": 25, "minFreeGb": 9}))

    def test_the_services_own_refusal_of_a_choice_reaches_the_owner_in_its_words(self):
        self.stack.quality_replies[("PUT", "/settings")] = (400, {"error": "The daily limit is between 1 and 500 albums."})
        r, data = self.call("PUT", "/admin/api/quality/settings", {"dailyCap": 0}, cookie=self.key)
        self.assertEqual((r.status, data["error"]), (400, "The daily limit is between 1 and 500 albums."))

    def test_the_check_everything_button_runs_the_self_test(self):
        self.stack.quality_replies[("POST", "/selftest")] = (200, {"ok": True, "checks": [{"key": "lidarr", "name": "Lidarr", "state": "ok", "note": ""}]})
        r, data = self.call("POST", "/admin/api/quality/selftest", {}, cookie=self.key)
        self.assertEqual((r.status, data["ok"]), (200, True))
        self.assertEqual(self.stack.quality_calls[-1][:2], ("POST", "/selftest"))

    def test_a_request_that_could_not_be_matched_can_be_sent_to_look_again(self):
        self.stack.quality_replies[("POST", "/requests/7/retry")] = (204, {})
        r, _ = self.call("POST", "/admin/api/quality/requests/7/retry", {}, cookie=self.key)
        self.assertEqual(r.status, 204)
        self.assertEqual(self.call("POST", "/admin/api/quality/requests/x/retry", {}, cookie=self.key)[0].status, 404)

    def test_when_the_service_is_there_but_does_not_answer_the_owner_is_told_to_try_again(self):
        self.stack.quality_up = False
        r, data = self.get()
        self.assertEqual((r.status, data["error"]), (502, "unreachable"))
        self.assertIn("Try again", data["message"])

    def test_wrong_methods_and_unknown_paths(self):
        self.assertEqual(self.call("POST", "/admin/api/quality", {}, cookie=self.key)[0].status, 405)
        self.assertEqual(self.call("GET", "/admin/api/quality/settings", cookie=self.key)[0].status, 405)
        self.assertEqual(self.call("GET", "/admin/api/quality/selftest", cookie=self.key)[0].status, 405)
        self.assertEqual(self.call("GET", "/admin/api/quality/other", cookie=self.key)[0].status, 404)

    def test_without_docker_the_page_still_works_when_the_service_answers(self):
        self.docker.stack_containers = None
        self.assertEqual(self.get()[0].status, 200)
        self.stack.quality_up = False
        self.assertEqual(self.get()[1], {"installed": False}, "no container list and no answer: not there")


class OnTheFrontPageTest(SiteTestBase):
    def today(self):
        key = self.sign_in()
        return self.call("GET", "/admin/api/today", cookie=key)[1]

    def test_a_working_quality_tier_with_soulseek_off_is_not_an_alarm(self):
        data = self.today()
        self.assertEqual(data["needsYou"], [])
        self.assertEqual(data["quality"]["soulseek"], False)
        part = next(p for p in data["parts"] if p["key"] == "quality")
        self.assertEqual(part["state"], "working")

    def test_a_server_without_it_shows_it_as_not_switched_on(self):
        del self.docker.stack_containers["encore-quality"]
        self.stack.quality_up = False
        data = self.today()
        part = next(p for p in data["parts"] if p["key"] == "quality")
        self.assertEqual((part["state"], part["note"]), ("off", "Not switched on."))
        self.assertIsNone(data["quality"])
        self.assertEqual(data["needsYou"], [])

    def test_soulseek_switched_on_but_not_connected_needs_the_owner(self):
        self.stack.quality_summary["settings"]["soulseek"] = True
        data = self.today()
        self.assertIn("Soulseek is switched on but not connected", data["needsYou"][0]["text"])
        self.assertEqual(data["needsYou"][0]["link"], "#/quality")

    def test_a_connected_soulseek_is_fine(self):
        self.stack.quality_summary["settings"]["soulseek"] = True
        self.stack.quality_summary["health"]["slskd"]["connected"] = True
        self.assertEqual(self.today()["needsYou"], [])

    def test_a_problem_the_service_names_is_shown_in_its_words(self):
        self.stack.quality_summary["health"]["problem"] = "Lidarr is not answering or refused its settings."
        data = self.today()
        self.assertEqual(data["needsYou"][0]["text"], "Best quality: Lidarr is not answering or refused its settings.")

    def test_songs_that_could_not_be_finished_are_counted_but_songs_nobody_shares_are_not_an_alarm(self):
        self.stack.quality_summary["counts"] = {"not_found": 5, "no_match": 3, "ready": 12}
        self.assertEqual(self.today()["needsYou"], [])
        self.stack.quality_summary["counts"] = {"failed": 2}
        self.assertEqual(self.today()["needsYou"][0]["text"], "Best quality: 2 songs could not be finished.")
        self.stack.quality_summary["counts"] = {"failed": 1}
        self.assertEqual(self.today()["needsYou"][0]["text"], "Best quality: 1 song could not be finished.")


if __name__ == "__main__":
    unittest.main()
