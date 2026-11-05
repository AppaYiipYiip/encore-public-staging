"""Why a song was not kept, in the words of the person who reads it (P2-22 part 1, docs/17 "Keep progress").

The scheduler stores a failure as the keeper raised it (`work_item.error`); this turns it into one short sentence and says whether trying again
can help. Two readers: the **Host** (role `owner`) can act on the cause, so the sentence names it; a **member** can do nothing about a server
setting, so the sentence says what happened to the song and nothing about how the server is set up.
"""

from __future__ import annotations

from dataclasses import dataclass

from .keeper import GIVE_UP, MUSIC_SERVER_DID_NOT_FIND, NOT_IN_MUSIC_FOLDER, TOO_LONG_AFTER, TOO_LONG_BEFORE


@dataclass(frozen=True)
class Failure:
    reason: str
    #: Whether asking again can work. False for what will not change however often it is tried (the song is gone, too long, too big).
    retry: bool


#: A keeper error code (a key of `GIVE_UP`) -> (what a member reads, what the Host reads). Every code must be here: a test fails when one is missing.
_BY_CODE = {
    "not_found": ("Not found.", "No upload of this song was found on YouTube."),
    "unavailable": ("Not available.", "YouTube has no copy of this song that can be fetched."),
    "age_restricted": ("Needs an age check.", "The only copy on YouTube needs an age check, which this server cannot pass."),
    "too_big": ("Too big to keep.", "The file is bigger than this server's limit for keeping a song."),
}
_TOO_LONG = ("Too long to keep.", "Longer than this server's limit for keeping a song, so it can be played but is not kept.")
_NOT_IN_FOLDER = ("Could not be saved.", "The saved file is not inside the music folder, so the music server cannot see it.")
_NOT_SEEN = (
    "The server could not finish saving it.",
    "The music server has not found the saved file. Check that its library includes the music folder.",
)
_OTHER = "Something went wrong on the server."


def describe_failure(error: str | None, *, host: bool) -> Failure:
    """The sentence for a failed keep, from the error the scheduler stored (`None` when it stored none)."""
    text = (error or "").strip()
    for code, stored in GIVE_UP.items():
        if text == stored:
            return Failure(_BY_CODE[code][1 if host else 0], False)
    if (
        text.startswith(TOO_LONG_BEFORE)
        and text.endswith(TOO_LONG_AFTER)
        and text[len(TOO_LONG_BEFORE) : -len(TOO_LONG_AFTER)].isdigit()
    ):
        return Failure(_TOO_LONG[1 if host else 0], False)
    if text == NOT_IN_MUSIC_FOLDER:
        return Failure(_NOT_IN_FOLDER[1 if host else 0], False)
    if text == MUSIC_SERVER_DID_NOT_FIND:
        return Failure(_NOT_SEEN[1 if host else 0], True)
    if host and text:
        return Failure(f"Something went wrong: {text[:200].rstrip('.')}.", True)
    return Failure(_OTHER, True)


def not_fetched() -> Failure:
    """A wanted song that nothing is fetching and that has no record of a try (it was added before the server could keep, or its record
    was cleared): honest, and a Retry starts it."""
    return Failure("The server has not fetched this song yet.", True)


def file_lost() -> Failure:
    """The server kept this song once and no longer has its file (a rescan dropped it, the file was deleted)."""
    return Failure("The server no longer has this song's file.", True)
