"""Getting the audio: yt-dlp for the song, a plain HTTPS GET for the cover."""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .cookies import Lease, as_source
from .resolve import Runner, RunResult, run_command

log = logging.getLogger("encore_fetch.download")

AUDIO_OUT = (".opus", ".m4a", ".mp3", ".ogg", ".aac", ".webm", ".flac")

# The best audio-only stream, untouched: Opus where YouTube has it (the
# library's own format), otherwise whatever is best.
FORMAT = "bestaudio[acodec=opus]/bestaudio"

# Cover art may only come from these hosts (a person's request must not make
# the server fetch arbitrary addresses).
COVER_HOSTS = (
    "dzcdn.net", "deezer.com", "ytimg.com", "ggpht.com",
    "googleusercontent.com", "coverartarchive.org", "archive.org",
)


@dataclass(frozen=True)
class Downloaded:
    path: Path
    codec: str
    bitrate_kbps: int | None


#: Containers YouTube's audio-only streams arrive in, in the order a live
#: reader looks for them.
_LIVE_EXT = (".webm", ".m4a", ".mp4", ".mp3", ".ogg", ".opus")


def live_source(stem: Path) -> tuple[Path, bool] | None:
    """The file a download of [stem] is being written to or was written to:
    `(path, still_being_written)`. A `.part` file is yt-dlp's work in
    progress; once it finishes the file is renamed, and a reader that keeps
    its offset simply carries on with the new name."""
    for ext in _LIVE_EXT:
        done = stem.with_name(stem.name + ext)
        if done.is_file():
            return done, False
        part = done.with_name(done.name + ".part")
        if part.is_file():
            return part, True
    return None


#: Marks lease arguments that are more than a cookies file (the in-process extractor cannot express them).
_OTHER_ARGS = object()


def cookiefile_of(args: list[str]):
    """The cookies file a lease asks for: `None` (a visitor), the path, or [_OTHER_ARGS] when the arguments say more than that."""
    if not args:
        return None
    if len(args) == 2 and args[0] == "--cookies":
        return args[1]
    return _OTHER_ARGS


class DownloadError(Exception):
    def __init__(self, code: str, message: str = "", account: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        #: The YouTube account the run used (a refusal is that account's, not the whole server's), if any.
        self.account = account


def classify_failure(stderr: str) -> str:
    s = stderr.lower()
    # Asked first: "Sign in to confirm your age" shares its start with the bot check ("Sign in to confirm you're not a
    # bot"), but it is about one video. On 2026-10-18 the real server said it for an age-gated song while a normal video
    # downloaded fine; calling it a block made an import rest for the whole server because of one song.
    if "age" in s and "restrict" in s or "confirm your age" in s:
        return "age_restricted"
    if "sign in to confirm" in s or "not a bot" in s or "http error 429" in s:
        return "blocked"
    if ("unavailable" in s or "private video" in s or "removed" in s
            or "not available" in s or "copyright" in s):
        return "unavailable"
    if "larger than max-filesize" in s or "max-filesize" in s:
        return "too_big"
    if "timeout" in s:
        return "timeout"
    return "download_failed"


def codec_of(path: Path) -> str:
    return {
        ".opus": "opus", ".ogg": "opus", ".webm": "opus", ".m4a": "aac",
        ".aac": "aac", ".mp3": "mp3", ".flac": "flac",
    }.get(path.suffix.lower(), path.suffix.lower().lstrip("."))


class YtDlpDownloader:
    def __init__(
        self,
        binary: str = "yt-dlp",
        *,
        cookies: object = None,
        max_file_mb: int = 80,
        runner: Runner = run_command,
        ffmpeg: str = "ffmpeg",
        timeout: int = 180,
        extractor: object | None = None,
        direct: bool = False,
    ) -> None:
        #: Fetch the saved stream address with plain ranged requests instead of starting yt-dlp again (direct.py).
        self._direct = direct
        #: Optional in-process extractor (lean.InProcessExtractor): used when no account cookies are involved.
        self._extractor = extractor
        self._binary = binary
        self._cookies = as_source(cookies)
        self._max_mb = max_file_mb
        self._run = runner
        self._ffmpeg = ffmpeg
        self._timeout = timeout

    def argv(self, video_id: str, stem: Path,
             info: Path | None = None, lease: Lease | None = None) -> list[str]:
        argv = [
            self._binary, "--no-playlist", "--no-warnings", "--no-progress",
            "-f", FORMAT,
            "--max-filesize", f"{self._max_mb}M",
            # No post-processing here: the file is written as it arrives so
            # the app can start playing it before it is complete; the remux
            # to .opus is done afterwards, by us.
            "-o", f"{stem}.%(ext)s",
        ]
        argv += (lease or self._cookies.lease(count=False)).args
        if info is not None:
            # An extraction saved earlier: no second round of YouTube pages.
            argv += ["--load-info-json", str(info)]
        else:
            argv += ["--", f"https://music.youtube.com/watch?v={video_id}"]
        return argv

    def extract(self, video_id: str, info: Path) -> None:
        """Asks YouTube for the song's streams and saves the answer to
        [info] (about 8 s on a slow line, almost all of it page downloads).
        A later [download] with `info=` starts in about a second."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
            raise DownloadError("bad_request", "bad video id")
        info.parent.mkdir(parents=True, exist_ok=True)
        lease = self._cookies.lease()
        cookies = cookiefile_of(lease.args)
        if self._extractor is not None and cookies is not _OTHER_ARGS:
            # Ask YouTube from inside this process (no program start, warm player code), as a visitor or with the account's cookies.
            try:
                self._extractor.extract(video_id, info, cookies)
            except DownloadError as error:
                lease.done("blocked" if error.code == "blocked" else "ok")
                raise
            lease.done("ok")
            return
        argv = [self._binary, "--no-playlist", "--no-warnings", "-f", FORMAT,
                "-j"]
        argv += lease.args
        argv += ["--", f"https://music.youtube.com/watch?v={video_id}"]
        result = self._run(argv, self._timeout)
        text = result.stdout.strip()
        if result.returncode != 0 or not text.startswith("{"):
            code = classify_failure(result.stderr)
            lease.done("blocked" if code == "blocked" else "ok")
            raise DownloadError(code, result.stderr[-300:], account=lease.account_id)
        lease.done("ok")
        info.write_text(text, encoding="utf-8")

    def _download_direct(self, info: Path, stem: Path) -> bool:
        """Tries the direct download; `False` (and nothing left behind) when the old way should run instead."""
        from .direct import DirectFailed, fetch  # late: direct.py imports this module

        try:
            data = json.loads(info.read_text(encoding="utf-8"))
            fetch(data, stem, max_bytes=self._max_mb * 1024 * 1024)
        except DirectFailed as error:
            log.info("direct download not used (%s); starting yt-dlp", error)
            return False
        except (OSError, ValueError) as error:
            log.info("direct download not used (%s: %s); starting yt-dlp", error.__class__.__name__, error)
            return False
        return True

    def download(self, video_id: str, stem: Path,
                 duration_s: int | None = None,
                 info: Path | None = None) -> Downloaded:
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
            raise DownloadError("bad_request", "bad video id")
        stem.parent.mkdir(parents=True, exist_ok=True)
        use = info if info is not None and info.is_file() else None
        # With a saved extraction the song was already counted (and asked of YouTube) by [extract].
        lease = self._cookies.lease(count=use is None)
        if use is not None and self._direct and self._download_direct(use, stem):
            result = RunResult(0, "", "")  # the bytes are here: carry on with the same finishing steps
        else:
            result = self._run(self.argv(video_id, stem, use, lease), self._timeout)
        if result.returncode != 0 and use is not None:
            # The saved extraction can go stale (its addresses expire after a
            # few hours): ask YouTube again, once.
            lease = self._cookies.lease()
            result = self._run(self.argv(video_id, stem, lease=lease), self._timeout)
        if result.returncode != 0:
            code = classify_failure(result.stderr)
            lease.done("blocked" if code == "blocked" else "ok")
            raise DownloadError(code, result.stderr[-300:], account=lease.account_id)
        lease.done("ok")
        found = live_source(stem)
        if found is None or found[1]:
            raise DownloadError("download_failed", "no audio file produced")
        path = found[0]
        if path.suffix.lower() == ".webm":
            # Opus in a WebM container -> the same Opus in an Ogg container
            # (what Navidrome and the rest of the library use). No
            # re-encoding. The .webm stays until the work folder is swept:
            # a player may still be reading it.
            out = path.with_suffix(".opus")
            r = self._run([self._ffmpeg, "-y", "-loglevel", "error", "-i",
                           str(path), "-vn", "-c:a", "copy", str(out)], 60)
            if r.returncode == 0 and out.exists():
                path = out
        size = path.stat().st_size
        if size > self._max_mb * 1024 * 1024:
            path.unlink(missing_ok=True)
            raise DownloadError("too_big")
        kbps = round(size * 8 / duration_s / 1000) if duration_s else None
        return Downloaded(path, codec_of(path), kbps)


def cover_url_ok(url: str | None) -> bool:
    if not url:
        return False
    try:
        u = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(
        host == h or host.endswith("." + h) for h in COVER_HOSTS)


def fetch_cover(url: str | None, *, max_bytes: int = 6 * 1024 * 1024,
                timeout: int = 10) -> bytes | None:
    """The cover image bytes, or `None` (covers are a nicety, never a
    reason to fail a song)."""
    if not cover_url_ok(url):
        return None
    try:
        req = urllib.request.Request(  # noqa: S310
            url, headers={"User-Agent": "encore-fetch/1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            data = r.read(max_bytes + 1)
        if len(data) > max_bytes or not data:
            return None
        return data
    except Exception:  # noqa: BLE001
        return None
