# 29 — Where Spotify does it better (gap review)

Owner, 2026-10-22, after trying the app: songs and albums were shown mixed together on an artist's page, there was no "Popular" section,
and "Spotify does this much better, and I'm sure it does other things much better." This page is the list of those other things, kept so
each becomes a task instead of a remark.

**How it was made.** From the planning agent's knowledge of Spotify's Android app, set against what Encore does today (read in the
code and walked on the emulator). It has **not** been checked side by side with a phone running Spotify: P4-12's acceptance is that the
owner does that and adds what is missing. Status words: **Have** (works, walked), **Partly** (exists, falls short), **Gap** (not there),
**Not ours** (Spotify has it, it does not fit a free, self-hosted app).

## Screens

| Area | What Spotify does | Encore today | Status | Where it goes |
|------|-------------------|--------------|--------|---------------|
| Artist page | Popular (5, "Show more"), Discography with filters (Popular releases / Albums / Singles and EPs / Compilations), Appears on, Fans also like, About with monthly listeners | **Fixed 2026-10-22 (build 112):** Popular (5, "Show more"), Albums, Singles and EPs, Compilations, each its own section, on the page of every artist. Still missing: Appears on, Fans also like, About, filter chips | Partly | P4-12 |
| Album page | Artist avatar and year in the header, total time, Save and Download toggles, "More by the artist", credits | Cover, songs, download, play; the header carries less | Partly | P4-12 |
| Search | Filter chips (Songs, Artists, Albums, Playlists), recent searches, good ranking: "Space Song" finds the one people mean | Top result and one list; **ranking misses**: "Beach House Space Song" and "Space Song" do not surface Beach House (walked 2026-10-22); no chips; no recent searches | Partly | P1-07, P2-12 |
| Devices | Its own "Connect to a device" sheet: this phone, speakers, other Spotify devices, each with a volume | The button opens **Android's own output switcher** (the dialog with "This phone" and "Connect a device"). It cannot be restyled: it belongs to the phone | Gap | P4-07 builds Encore's own Devices sheet; the system switcher stays one tap away for Bluetooth |
| Now playing | Swipe between tracks, a lyrics preview card, About the artist, credits, song radio, "Add to playlist" with ticks on the lists it is already in, share cards | Cover, seek bar, Lyrics, Sleep timer (in the ⋯ menu), Queue, like (the Devices button, Speed and Private were taken out of the player by D-28 and D-23, 2026-10-30); no song radio, no credits, no share card | Partly | P4-12 |
| Lyrics | Full screen, synced, a share button, licensed from a lyrics company so nearly every song has them | Full screen, synced, size setting. **Coverage is the gap**: the free source (LRCLIB) has no entry for many songs (Alonzo "DLG" on 2026-10-22; it does have Radiohead and Gojira). The empty state says so honestly | Partly | P2-14: read lyrics stored with the song (`.lrc` next to a file, tags), keep what was found on the server, let a person paste their own |
| Home | Shelves made for the person (Daily Mix, "Jump back in", new releases of followed artists), recently played grid | Liked Songs and recent playlists, "New from artists you play", Year in Music; recommendations are P4-01 | Partly | P4-01 |
| Library | Filter chips (Playlists, Albums, Artists, Downloaded), sort (recent, alphabetical, creator), grid or list, pinned items, folders | Tabs and a Downloaded list of playlists/albums; no sort or filter chips, pins exist for some lists | Partly | P4-12 |
| Playlists | Collaborative, recommended songs at the bottom, custom cover, sort, download toggle | Edit, reorder, mosaic cover, download; collaborative is P4-10 | Partly | P4-10, P4-12 |
| Offline | Smart downloads, "download all liked songs" that follows new likes | Per playlist/album download, offline library | Partly | P4-12 |
| Playback | Crossfade, gapless, equalizer, normalise volume, audio quality per network | Gapless, equalizer, loudness levelling, speed, sleep timer; no crossfade | Partly | P4-12 |
| Sharing | Link previews, Spotify Codes | Invitation link and QR; no song or playlist share card | Gap | P4-12 |
| Connect | Control the tablet from the phone | Planned | Gap | P4-07 |
| Jam | Group session | Built on the old server, proven there; not on the new one | Partly | P4-02 |
| Year in Music | Wrapped | Built on the old server; from the new server's plays is P4-05 | Partly | P4-05 |
| Cars, watches, widgets | Android Auto, Wear OS, a home-screen widget | Android Auto search and a widget are listed | Gap | P4-12 |
| Podcasts, video, ads, Premium | Yes | No, by design | Not ours | — |

## What this review changes in the plan

1. P1-07 (search) now has a measured miss to fix first: an artist-and-title query must rank the real artist's song above songs that merely
   contain the words.
2. P2-14 (lyrics on the server) gets the coverage problem as its reason: the lookup is only as good as LRCLIB, so the server must also
   read lyrics kept with the music and remember what was found.
3. P4-07 keeps its Devices sheet; the answer to "can we change this screen?" is yes for Encore's own sheet, no for Android's.
4. P4-12 starts from this table, and its acceptance (the owner compares side by side and lists gaps) adds rows here.
