"""The container's start-up script: yt-dlp is updated when the service starts AND while it keeps running (YouTube changes
often; a service that stays up for weeks must not keep the version it started with). Run with stand-ins for pip and python."""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parent.parent / "entrypoint.sh"
SH = shutil.which("sh")


@unittest.skipUnless(SH, "needs a POSIX shell")
class EntrypointTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls.log"

    def stand_in(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def run_entrypoint(self, *, lives_seconds: int, every: str, pip_fails: bool = False) -> list[str]:
        self.stand_in("pip", f'echo "pip $*" >> "{self.log.as_posix()}"\n' + ("exit 1\n" if pip_fails else "exit 0\n"))
        self.stand_in("python", f'echo "python $*" >> "{self.log.as_posix()}"\nsleep {lives_seconds}\n')
        env = {**os.environ, "PATH": f"{self.bin.as_posix()}{os.pathsep}{os.environ['PATH']}",
               "HOME": (self.root / "home").as_posix(), "YTDLP_UPDATE_EVERY": every}
        # The script makes /work; point it somewhere writable for the test.
        script = ENTRYPOINT.read_text(encoding="utf-8").replace("/work", (self.root / "work").as_posix())
        run = self.root / "entrypoint.sh"
        run.write_text(script, encoding="utf-8", newline="\n")
        # No pipes: the reminder loop is a child of the script and would hold a pipe open until it ends.
        subprocess.run([SH, run.as_posix()], env=env, timeout=60, check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def test_updates_at_start_then_runs_the_service(self) -> None:
        # A short interval everywhere: the loop only ends when it next wakes, and it must not linger after the test.
        calls = self.run_entrypoint(lives_seconds=0, every="1")
        self.assertTrue(calls[0].startswith("pip install"), calls)
        self.assertIn("--upgrade yt-dlp", calls[0])
        self.assertIn("python -m encore_fetch", calls)

    def test_looks_for_a_newer_yt_dlp_while_the_service_keeps_running(self) -> None:
        calls = self.run_entrypoint(lives_seconds=4, every="1")
        pips = [c for c in calls if c.startswith("pip ")]
        self.assertGreaterEqual(len(pips), 3, calls)  # at start, and again every second the service is up

    def test_stops_looking_when_the_service_has_stopped(self) -> None:
        # The service lives 3 s and the loop looks every 2 s: its first look is at about 2 s, its second would be at about 4 s, a whole
        # second after the service ended. (With 2 s and 1 s the second look fell exactly when the service ended; whenever the loop won
        # that race by a few milliseconds its last "pip show" was written after the count below was read, and the test failed at random.)
        self.run_entrypoint(lives_seconds=3, every="2")
        settled = self.log.read_text(encoding="utf-8").count("pip ")
        time.sleep(2.5)
        self.assertEqual(self.log.read_text(encoding="utf-8").count("pip "), settled,
                         "the reminder loop must not outlive the service")

    def test_a_failed_update_never_stops_the_service(self) -> None:
        calls = self.run_entrypoint(lives_seconds=0, every="1", pip_fails=True)
        self.assertIn("python -m encore_fetch", calls)


if __name__ == "__main__":
    unittest.main()
