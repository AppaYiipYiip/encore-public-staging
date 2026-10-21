"""The front page as an owner reads it (docs/49 P1): is everything working, and if not, which part and what to do. A part that was
never switched on is not an alarm; a part that is switched on and does not answer is."""
import unittest

from encore_admin.docker_api import Docker, DockerError

from tests.fakes import FakeDocker
from tests.test_site import SiteTestBase


class WhatRunsTest(unittest.TestCase):
    def test_only_the_known_parts_of_the_stack_are_reported_with_their_state(self):
        fake = FakeDocker()
        fake.stack_containers["some-other-app"] = ("running", "Up 1 day")
        fake.stack_containers["encore-hub"] = ("exited", "Exited (1) 5 minutes ago")
        fake.stack_containers["navidrome"] = ("running", "Up 2 minutes (health: starting)")
        found = Docker(fake, fake, "img:1").stack()
        self.assertNotIn("some-other-app", found)
        self.assertEqual(found["encore-hub"], "stopped")
        self.assertEqual(found["navidrome"], "starting")
        self.assertEqual(found["encore-people"], "running")
        self.assertEqual(found["encore-tailscale"], "running")

    def test_a_restarting_container_is_not_called_running(self):
        fake = FakeDocker()
        fake.stack_containers["encore-fetch"] = ("restarting", "Restarting (1) 4 seconds ago")
        self.assertEqual(Docker(fake, fake, "img:1").stack()["encore-fetch"], "restarting")

    def test_a_container_marked_unhealthy_is_said_to_be(self):
        fake = FakeDocker()
        fake.stack_containers["encore-tailscale"] = ("running", "Up 3 hours (unhealthy)")
        self.assertEqual(Docker(fake, fake, "img:1").stack()["encore-tailscale"], "unhealthy")

    def test_when_docker_cannot_be_asked_that_is_an_error_not_an_empty_stack(self):
        fake = FakeDocker()
        fake.stack_containers = None
        with self.assertRaises(DockerError):
            Docker(fake, fake, "img:1").stack()

    def test_asking_only_reads(self):
        fake = FakeDocker()
        Docker(fake, fake, "img:1").stack()
        self.assertEqual([m for m, _, _ in fake.calls], ["GET"])


class TheFrontPageTest(SiteTestBase):
    def today(self):
        key = self.sign_in()
        r, data = self.call("GET", "/admin/api/today", cookie=key)
        self.assertEqual(r.status, 200, data)
        return data

    def part(self, data, key):
        return next(p for p in data["parts"] if p["key"] == key)

    def test_when_everything_runs_each_part_is_working_and_nothing_needs_the_owner(self):
        data = self.today()
        self.assertEqual([p["key"] for p in data["parts"]], ["music", "people", "fetch", "quality", "recs", "hub", "remote"])
        self.assertEqual({p["state"] for p in data["parts"]}, {"working"})
        self.assertEqual(data["needsYou"], [])
        self.assertEqual(data["server"], "Encore")

    def test_every_part_has_a_plain_name(self):
        names = {p["key"]: p["name"] for p in self.today()["parts"]}
        self.assertEqual(names, {"music": "Music server", "people": "People and invitations", "fetch": "Songs from YouTube",
                                 "quality": "Best quality (Lidarr and Soulseek)", "recs": "Suggestions for each person",
                                 "hub": "Jam (listening together)",
                                 "remote": "Reaching it from outside"})

    def test_a_part_that_was_never_switched_on_is_off_and_is_not_an_alarm(self):
        del self.docker.stack_containers["encore-hub"]
        self.stack.server_parts["hub"] = {"up": False}
        data = self.today()
        self.assertEqual(self.part(data, "hub")["state"], "off")
        self.assertEqual(self.part(data, "hub")["note"], "Not switched on.")
        self.assertEqual(data["needsYou"], [])

    def test_a_part_that_is_switched_on_but_does_not_answer_needs_the_owner(self):
        self.stack.fetch_up = False
        data = self.today()
        self.assertEqual(self.part(data, "fetch")["state"], "down")
        self.assertEqual(data["needsYou"][0]["text"], "Songs from YouTube is not answering. It usually comes back by itself; if it does not, restart it.")

    def test_a_part_that_is_still_starting_is_told_to_wait_not_to_worry(self):
        self.docker.stack_containers["navidrome"] = ("running", "Up 10 seconds (health: starting)")
        self.stack.fetch_up = False
        self.docker.stack_containers["encore-fetch"] = ("running", "Up 5 seconds")
        data = self.today()
        self.assertEqual(self.part(data, "fetch")["state"], "starting")
        self.assertEqual(data["needsYou"], [], "give it a minute")

    def test_a_part_that_keeps_stopping_is_not_called_working(self):
        self.docker.stack_containers["encore-people"] = ("restarting", "Restarting (1) 3 seconds ago")
        self.stack.people_up = False
        data = self.today()
        self.assertEqual(self.part(data, "people")["state"], "down")
        self.assertTrue(any("People and invitations" in n["text"] for n in data["needsYou"]))

    def test_the_other_parts_still_show_when_the_people_service_is_down(self):
        self.stack.people_up = False
        data = self.today()
        self.assertEqual(self.part(data, "music")["state"], "working", "the owner just signed in to it")
        self.assertEqual(self.part(data, "fetch")["state"], "working")
        self.assertIsNone(data["people"])

    def test_the_remote_address_is_working_when_its_container_is_healthy(self):
        self.assertEqual(self.part(self.today(), "remote")["state"], "working")
        self.docker.stack_containers["encore-tailscale"] = ("running", "Up 3 hours (unhealthy)")
        data = self.today()
        self.assertEqual(self.part(data, "remote")["state"], "down")
        self.assertTrue(any("Reaching it from outside" in n["text"] for n in data["needsYou"]))

    def test_without_docker_the_answering_parts_are_still_working_and_the_rest_are_not_guessed(self):
        self.docker.stack_containers = None
        data = self.today()
        self.assertEqual(self.part(data, "fetch")["state"], "working")
        self.assertEqual(self.part(data, "remote")["state"], "unknown")
        self.assertEqual(data["needsYou"], [], "not knowing is not an alarm")
        self.stack.fetch_up = False
        data = self.today()
        self.assertEqual(self.part(data, "fetch")["state"], "down", "a part that does not answer is down whatever Docker says")

    def test_the_songs_service_flag_the_old_page_used_still_means_the_same(self):
        self.assertTrue(self.today()["songsServiceUp"])
        self.stack.fetch_up = False
        self.assertFalse(self.today()["songsServiceUp"])

    def test_the_server_answer_gives_the_address_a_friend_would_type(self):
        data = self.today()
        self.assertEqual(data["address"], "https://music.example.ts.net")


if __name__ == "__main__":
    unittest.main()
