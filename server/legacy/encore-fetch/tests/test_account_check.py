"""The "does this account really work?" check."""
import subprocess
import unittest
from pathlib import Path

from encore_fetch.account_test import check_account



def done(code=0, err="", out=""):
    return subprocess.CompletedProcess([], code, out, err)


class CheckAccountTest(unittest.TestCase):
    def run_check(self, *answers):
        queue = list(answers)
        calls = []

        def runner(argv, timeout):
            calls.append(argv)
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        return check_account("yt-dlp", Path("/work/youtube/abc.txt"), run=runner), calls

    def test_an_account_that_is_recognised_and_can_fetch_works(self):
        result, calls = self.run_check(done(0, out="someid"), done(0, out="A song"))
        self.assertEqual((result["ok"], result["login"], result["fetch"]), (True, True, True))
        self.assertIn("Works", result["message"])
        self.assertIn("--cookies", calls[0])
        self.assertIn(":ythis", calls[0])
        self.assertIn("-s", calls[1], "the song is only looked at, never downloaded")

    def test_a_sign_in_youtube_does_not_recognise_says_to_sign_in_again(self):
        result, calls = self.run_check(done(1, err="ERROR: [youtube:history] Login details are needed to download this content."))
        self.assertEqual((result["ok"], result["login"]), (False, False))
        self.assertIn("Sign in again", result["message"])
        self.assertEqual(len(calls), 1)

    def test_signed_in_but_unable_to_fetch_says_the_server_is_at_fault_not_the_account(self):
        result, _ = self.run_check(done(0), done(1, err="ERROR: [youtube] x: The page needs to be reloaded."))
        self.assertEqual((result["login"], result["fetch"], result["ok"]), (True, False, False))
        self.assertIn("this server could not solve YouTube's player", result["message"])

    def test_a_bot_check_is_said_as_a_person_check(self):
        result, _ = self.run_check(done(0), done(1, err="ERROR: Sign in to confirm you're not a bot"))
        self.assertIn("prove it is a person", result["message"])

    def test_a_timeout_is_a_sentence(self):
        result, _ = self.run_check(subprocess.TimeoutExpired("yt-dlp", 90))
        self.assertIn("did not answer in time", result["message"])
        result, _ = self.run_check(done(0), subprocess.TimeoutExpired("yt-dlp", 90))
        self.assertEqual((result["login"], result["ok"]), (True, False))

    def test_yt_dlps_own_words_never_reach_the_owner(self):
        result, _ = self.run_check(done(0), done(1, err="ERROR: [youtube] secret-looking /usr/local/lib/python3.12/x.py line 4"))
        self.assertNotIn("/usr/local", result["message"])
        self.assertNotIn("Traceback", result["message"])


if __name__ == "__main__":
    unittest.main()
