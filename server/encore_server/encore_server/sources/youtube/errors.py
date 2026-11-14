"""What can go wrong fetching from YouTube, as codes (docs/17: `song_unavailable`, `source_busy`, ...)."""

from __future__ import annotations

#: The bytes asked for: the best audio-only stream, Opus where YouTube has it (the library's own format).
FORMAT = "bestaudio[acodec=opus]/bestaudio"


class DownloadError(Exception):
    """`code` is one of: not_found (the search ANSWERED and nothing acceptable matched), unavailable, age_restricted (the upload is gone, or needs an age check),
    search_failed (the search itself could not be made: says nothing about the song), blocked, too_big, timeout, download_failed, disk_full, no_library."""

    def __init__(self, code: str, message: str = "", account: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        #: The YouTube account the run used (a refusal is that account's, not the whole server's), if any.
        self.account = account


def classify_failure(stderr: str) -> str:
    s = stderr.lower()
    # Asked first: "Sign in to confirm your age" shares its start with the bot check ("Sign in to confirm you're not a bot"), but it is
    # about one video. Calling it a block made an import rest for the whole server because of one song (2026-10-18).
    if "age" in s and "restrict" in s or "confirm your age" in s:
        return "age_restricted"
    if "sign in to confirm" in s or "not a bot" in s or "http error 429" in s:
        return "blocked"
    if "unavailable" in s or "private video" in s or "removed" in s or "not available" in s or "copyright" in s:
        return "unavailable"
    if "larger than max-filesize" in s or "max-filesize" in s:
        return "too_big"
    if "timeout" in s:
        return "timeout"
    return "download_failed"
