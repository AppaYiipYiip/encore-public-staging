"""The People page of the admin (docs/48): the owner sees who is on the server, adds a person, resets a password, locks, removes, invites."""
import json
import unittest

from tests.test_site import SiteTestBase


class PeopleTestBase(SiteTestBase):
    def setUp(self):
        super().setUp()
        self.key = self.sign_in()
        self.stack.people_replies[("GET", "/api/people")] = (200, {"people": [
            {"user": "owner", "role": "owner", "fixed": True, "invitedBy": None, "joinedAt": None, "createdAt": 1.0, "lastAccess": 2.0,
             "paused": False, "mustChange": False, "resetAsked": None},
            {"user": "sam", "role": "guest", "fixed": False, "invitedBy": "owner", "joinedAt": 3.0, "createdAt": 3.0, "lastAccess": None,
             "paused": False, "mustChange": False, "resetAsked": 100.0}]})
        self.stack.people_replies[("GET", "/api/resets")] = (200, {"requests": [{"user": "sam", "askedAt": 100.0}]})
        self.stack.people_replies[("GET", "/api/invites")] = (200, {"invites": [{"id": 7, "state": "open", "role": "guest"}]})

    def post(self, path, body=None):
        return self.call("POST", "/admin/api/people" + path, body if body is not None else {}, cookie=self.key)

    def asked(self):
        return [(m, p, b) for m, p, q, b in self.stack.people_calls]


class TheListTest(PeopleTestBase):
    def test_the_owner_sees_everybody_the_requests_for_help_and_the_open_invitations_in_one_look(self):
        r, data = self.call("GET", "/admin/api/people", cookie=self.key)
        self.assertEqual(r.status, 200)
        self.assertEqual([p["user"] for p in data["people"]], ["owner", "sam"])
        self.assertEqual(data["people"][1]["invitedBy"], "owner")
        self.assertEqual([x["user"] for x in data["requests"]], ["sam"])
        self.assertEqual(data["invites"][0]["id"], 7)
        self.assertTrue(data["inviteLinks"])

    def test_it_is_asked_as_the_owner_and_never_with_the_password(self):
        self.call("GET", "/admin/api/people", cookie=self.key)
        self.assertTrue(self.stack.people_calls)
        for method, path, query, body in self.stack.people_calls:
            self.assertEqual(query["u"], "dana")
            self.assertNotIn("correct horse", json.dumps(query))

    def test_without_a_public_address_the_page_says_invitations_by_link_are_not_available(self):
        self.stack.people_replies[("GET", "/api/info")] = (200, {"service": "encore-people", "inviteLinks": False})
        data = self.call("GET", "/admin/api/people", cookie=self.key)[1]
        self.assertFalse(data["inviteLinks"])

    def test_the_page_needs_the_owners_session_and_the_people_service(self):
        self.assertEqual(self.call("GET", "/admin/api/people")[0].status, 401)
        self.stack.people_up = False
        r, data = self.call("GET", "/admin/api/people", cookie=self.key)
        self.assertEqual((r.status, data["error"]), (502, "unreachable"))
        self.assertIn("people service", data["message"])


class DoingThingsTest(PeopleTestBase):
    def test_adding_a_person_hands_back_the_temporary_password_once(self):
        self.stack.people_replies[("POST", "/api/people")] = (201, {"user": "tom", "temporaryPassword": "river-lamp-orange-slow-47"})
        r, data = self.post("", {"name": "tom", "role": "inviter"})
        self.assertEqual((r.status, data["temporaryPassword"]), (201, "river-lamp-orange-slow-47"))
        self.assertEqual(self.asked(), [("POST", "/api/people", {"name": "tom", "role": "inviter"})])

    def test_a_sentence_from_the_people_service_reaches_the_owner(self):
        self.stack.people_replies[("POST", "/api/people")] = (409, {"error": "That name is already taken. Choose another."})
        r, data = self.post("", {"name": "sam"})
        self.assertEqual((r.status, data["error"]), (409, "That name is already taken. Choose another."))

    def test_resetting_locking_unlocking_and_changing_a_role(self):
        self.stack.people_replies[("POST", "/api/people/sam/password")] = (200, {"temporaryPassword": "x-y-z-w-11"})
        self.assertEqual(self.post("/sam/password", {"mode": "temporary"})[1]["temporaryPassword"], "x-y-z-w-11")
        self.stack.people_replies[("POST", "/api/people/sam/password")] = (200, {"code": "abc", "url": "https://h/people/reset/abc", "expiresAt": 9.0})
        self.assertEqual(self.post("/sam/password", {"mode": "link"})[1]["url"], "https://h/people/reset/abc")
        self.stack.people_replies[("POST", "/api/people/sam/lock")] = (204, {})
        self.assertEqual(self.post("/sam/lock")[0].status, 204)
        self.stack.people_replies[("POST", "/api/people/sam/unlock")] = (200, {"temporaryPassword": "a-b-c-d-22"})
        self.assertEqual(self.post("/sam/unlock")[1]["temporaryPassword"], "a-b-c-d-22")
        self.stack.people_replies[("PUT", "/api/people/sam")] = (204, {})
        self.assertEqual(self.post("/sam/role", {"role": "inviter"})[0].status, 204)
        self.assertIn(("PUT", "/api/people/sam", {"role": "inviter"}), self.asked())

    def test_removing_a_person_is_a_delete_on_the_people_service(self):
        self.stack.people_replies[("DELETE", "/api/people/sam")] = (204, {})
        self.assertEqual(self.post("/sam/remove")[0].status, 204)
        self.assertIn(("DELETE", "/api/people/sam", None), self.asked())

    def test_invitations_are_made_and_taken_back(self):
        self.stack.people_replies[("POST", "/api/invites")] = (201, {"id": 8, "url": "https://h/people/join/xyz", "expiresAt": 5.0, "role": "guest"})
        r, data = self.call("POST", "/admin/api/invites", {"role": "guest"}, cookie=self.key)
        self.assertEqual((r.status, data["url"]), (201, "https://h/people/join/xyz"))
        self.stack.people_replies[("DELETE", "/api/invites/8")] = (204, {})
        self.assertEqual(self.call("POST", "/admin/api/invites/8/revoke", {}, cookie=self.key)[0].status, 204)

    def test_a_request_for_help_can_be_dismissed(self):
        self.stack.people_replies[("DELETE", "/api/resets/sam")] = (204, {})
        self.assertEqual(self.call("POST", "/admin/api/resets/sam/dismiss", {}, cookie=self.key)[0].status, 204)

    def test_names_that_could_change_the_path_are_refused_before_they_leave_this_page(self):
        for bad in ("..", "sam%2F..%2Fx", "a b", "x" * 80, ".."):
            r, data = self.post(f"/{bad}/lock")
            self.assertIn(r.status, (400, 404), bad)
        self.assertEqual(self.stack.people_calls, [])
        self.assertEqual(self.post("/sam/explode")[0].status, 404)
        self.assertEqual(self.call("GET", "/admin/api/people/sam/lock", cookie=self.key)[0].status, 405)

    def test_what_changes_things_needs_the_sites_own_header_and_a_session(self):
        r, data = self.call("POST", "/admin/api/people/sam/lock", {}, cookie=self.key, headers={"X-Encore-Admin": ""})
        self.assertEqual(r.status, 403)
        self.assertEqual(self.call("POST", "/admin/api/people/sam/lock", {})[0].status, 401)
        self.assertEqual(self.stack.people_calls, [])


class TheFrontPageTest(PeopleTestBase):
    def test_a_person_who_forgot_their_password_is_a_card_that_needs_the_owner(self):
        data = self.call("GET", "/admin/api/today", cookie=self.key)[1]
        self.assertIn({"text": "sam asked for a new password", "link": "#/people"}, data["needsYou"])
        self.assertEqual(data["people"], {"count": 2, "asking": 1})

    def test_the_front_page_still_works_when_the_people_service_is_not_there(self):
        self.stack.people_up = False
        data = self.call("GET", "/admin/api/today", cookie=self.key)[1]
        self.assertIsNone(data["people"])


if __name__ == "__main__":
    unittest.main()
