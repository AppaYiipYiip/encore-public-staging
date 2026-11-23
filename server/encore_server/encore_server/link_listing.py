"""What one pass of the library link saw of the music server, and which file rows that leaves alive (P2-25 slice 4, review round 2).

The library link reads the music server's whole listing page by page. **A row of `song_file` with a music server id is alive in this pass when the music server lists that id
(or the row was attached after the pass began, or has no music server id at all); a row it does not list is gone: the hourly pass that prunes removes it, and a pass that
only adds (the one after a scan) will see the next pass that prunes remove it.** This is the ONE definition: `scanner._prune` removes the rows that are not alive, and the
rehome counts only alive rows as files a song keeps (the last-file guard, the preferred file, the files a ref is released for). Before it was written once, the guard
counted a row the prune removed in the same pass: a liked song kept its like and lost its only listed file to a move (audit probe 6).

The listing is complete only when the music server has answered every page: a pass that stopped early decides nothing from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Listing:
    #: When the pass began (ms): a row attached after it (the keeper, mid-scan) is left alone by the prune and is alive.
    began: int
    #: Every id of the music server the pass has seen so far, whatever its tags are (a file the music server lists with tags nobody can describe is not gone).
    seen: set[str] = field(default_factory=set)
    #: The music server answered every page: only then is `seen` the whole listing.
    complete: bool = False

    def add(self, navidrome_song_id: str) -> None:
        self.seen.add(navidrome_song_id)

    def alive(self, navidrome_song_id: str | None, added_at: int) -> bool:
        """Does this file row survive the pass? A row with no music server id cannot be pruned; a row attached after the pass began is not judged by a listing that was
        read before it existed; every other row lives exactly when the music server lists its id."""
        return navidrome_song_id is None or added_at >= self.began or navidrome_song_id in self.seen

    @classmethod
    def of(cls, songs: list[dict[str, object]], *, began: int) -> Listing:
        """A COMPLETE listing of these songs (the music server's own dicts); for a caller that has the whole listing in hand."""
        return cls(began=began, seen={str(song.get("id")) for song in songs if song.get("id")}, complete=True)
