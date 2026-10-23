"""The check a newer yt-dlp has to pass before the server switches to it (docs/11 ADR-R39).

It runs in a **child process** whose import path starts with the candidate wheel, so the running server is never touched, and it goes through the
same code that plays a song: the server's own `YoutubeSource` (the same format selector, the same fast client, the same stream proxy), on one fixed
short video that is not music, reading the first 64 KB of its audio. A pass means "the path that plays songs works with this yt-dlp today".

The child has no pacer, no rest and no look-up counter of its own, so the parent takes the pacer's turn, honours the rest and counts the look-up
(`rest.Guarded` around [ChildCanary], see updater.py).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import DownloadError

#: Blender Foundation's "Big Buck Bunny": an open film (CC BY) on the Foundation's own channel, not somebody's music, and playable through the very path songs take.
#: Chosen after the first real run (2026-10-23): YouTube's first upload ("Me at the zoo") answered "This video is unavailable" on that path (yt-dlp 2026.8.19 by hand,
#: and the updater's own check of 2026.10.21 said "not available" too), while this one passed with 2026.10.21 (65536 bytes).
CANARY_VIDEO = "aqz-KE-bpKQ"
READ_BYTES = 64 * 1024
#: What the child's [StreamError] codes become on the parent's side (the codes of `DownloadError`).
_FROM_STREAM = {
    "not_found": "not_found",
    "unavailable": "unavailable",
    "age_restricted": "age_restricted",
    "blocked": "blocked",
    "slow": "timeout",
}


def child_env(wheel: Path | None, active: Path | None, base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment of a child that must use [wheel] (a candidate), or - with no wheel - the copy this process runs ([active], or the image's)."""
    env = dict(os.environ if base is None else base)
    paths = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and (active is None or p != str(active))]
    first = wheel if wheel is not None else active
    if first is not None:
        paths.insert(0, str(first))
    if paths:
        env["PYTHONPATH"] = os.pathsep.join(paths)
    else:
        env.pop("PYTHONPATH", None)
    return env


class ChildCanary:
    """An extractor for `rest.Guarded`: the canary run in a child process. Keeps the version the child reported in [version]."""

    def __init__(
        self,
        wheel: Path | None,
        *,
        active: Path | None = None,
        run: Callable[..., Any] = subprocess.run,
        timeout_s: float = 150.0,
    ) -> None:
        self._wheel = wheel
        self._active = active
        self._run = run
        self._timeout = timeout_s
        self.version: str | None = None

    def extract(self, video_id: str, info: Path, cookiefile: str | None = None) -> None:
        argv = [sys.executable, "-m", "encore_server.sources.youtube.canary", video_id]
        try:
            done = self._run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                env=child_env(self._wheel, self._active),
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise DownloadError("timeout", "the check took longer than it may") from error
        except OSError as error:
            raise DownloadError("download_failed", f"the check could not be started: {error}") from error
        lines = [line for line in (done.stdout or "").splitlines() if line.strip()]
        try:
            answer = json.loads(lines[-1])
            ok = bool(answer["ok"])
        except (IndexError, ValueError, KeyError, TypeError) as error:
            tail = ((done.stderr or "").strip().splitlines() or ["no answer"])[-1][-200:]
            raise DownloadError("download_failed", f"the check gave no answer ({tail})") from error
        version = answer.get("version")
        self.version = version if isinstance(version, str) else None
        if not ok:
            raise DownloadError(str(answer.get("code") or "download_failed"), str(answer.get("message") or "")[-300:])


# ---------------------------------------------------------------------------------------------------- the child


def check(video_id: str, *, source_factory: Callable[[Path], Any] | None = None) -> dict[str, Any]:
    """What the child answers: `{"ok": true, "version", "bytes"}` or `{"ok": false, "code", "message", "version"}`."""
    version: str | None = None
    try:
        import yt_dlp.version

        version = yt_dlp.version.__version__
    except Exception as error:  # noqa: BLE001 - whatever is wrong with the copy is the answer
        return {"ok": False, "code": "download_failed", "message": f"yt-dlp cannot be imported: {error}", "version": None}
    from .stream import StreamError

    try:
        with tempfile.TemporaryDirectory(prefix="encore-canary-") as tmp:
            if source_factory is not None:
                source = source_factory(Path(tmp))
            else:
                from .source import YoutubeSource

                source = YoutubeSource(Path(tmp), fast_clients=("visionos",))
            from .source import Wanted

            upstream = source.open(
                Wanted(ref_id="canary", artist="", title="canary", album=None, duration_s=None, video_id=video_id),
                f"bytes=0-{READ_BYTES - 1}",
            )
            got = 0
            try:
                for chunk in upstream.body:
                    got += len(chunk)
                    if got >= READ_BYTES:
                        break
            finally:
                upstream.close()
    except StreamError as error:
        return {
            "ok": False,
            "code": _FROM_STREAM.get(error.code, "download_failed"),
            "message": error.message,
            "version": version,
        }
    except DownloadError as error:
        return {"ok": False, "code": error.code, "message": str(error), "version": version}
    except Exception as error:  # noqa: BLE001 - an unexpected failure is a failed check, not a crash without an answer
        return {"ok": False, "code": "download_failed", "message": f"{type(error).__name__}: {error}", "version": version}
    if got < 1024:
        return {"ok": False, "code": "download_failed", "message": f"only {got} bytes of audio came", "version": version}
    return {"ok": True, "version": version, "bytes": got}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    print(json.dumps(check(args[0] if args else CANARY_VIDEO)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
