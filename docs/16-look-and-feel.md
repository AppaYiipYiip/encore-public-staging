# 16 — Look and feel: making Encore feel alive

Owner, 2026-10-21: *"should we include some art? make it more alive?"* Yes, with one rule: **the music is the art.** Spotify, Plexamp and
Apple Music feel alive because the screen is full of the music's own colours and covers, moving gently. Encore has an advantage:
it can show *your* music (the Host's library, your imports) instead of stock pictures.

The final name and logo are not decided (owner: "not now"); everything here works with the current placeholder mark and the design
tokens in `app/lib/design/tokens.dart` (accent `#19E68C`, dark background `#0E0E10`, Figtree font under the SIL Open Font Licence).

## 1. Personality

| Is | Is not |
|----|--------|
| Warm, at home, musical | Technical, "server admin" |
| Calm, confident, quick | Busy, flashy, noisy |
| Plain and friendly words ("Your music is ready") | Jargon or jokes |
| Personal (your covers, your server's name and colour) | Generic stock imagery |

## 2. Five sources of life, in order of importance

1. **Covers everywhere, never letters.** Every row, card and player shows real artwork (P1-10). The golden-ratio cover mosaic that
   already exists (`mosaic_layout.dart`, R-09) makes playlists, the setup's last page and the app's welcome screen out of the person's
   own music. Letter tiles are a bug, not a style.
2. **Colour from the music.** The full player, album and playlist headers already take their colour from the artwork (ADR-011); extend
   it to the mini-player (a thin tinted bar), the lock-screen-style lyrics page, the Jam screen (the current song's colour for
   everyone in the Jam) and the setup wizard's last page (the library's dominant colours).
3. **Gentle motion with meaning.**
   * The logo's sound bars move to the music on the welcome screen and while something loads (one cheap animation, ≤ 2 ms per frame,
     never on a page that is just waiting for the network for long — then a still state with a sentence).
   * Now-playing rows: small animated bars on the song that plays.
   * Moving between a cover and its page: the cover grows into the header (shared-element transition).
   * The background cover wall on Welcome and "All set": slow drift (30–60 s per screen width), blurred, darkened.
   * Success moments (setup finished, first import ready, a Jam started): one short, quiet celebration (a ripple of covers or a
     soft burst of the accent colour), never confetti on routine actions.
   * **Respect "Remove animations"** in Android's accessibility settings: everything becomes a cross-fade or nothing.
4. **A small set of illustrations** for moments without music yet: setup pages (house with notes, search with a note, suitcase with
   headphones, two houses sharing a note, phone + tablet), empty states (no playlists yet, offline, nothing found), errors.
   * Style: simple shapes, two tones of the background plus the accent, rounded, no faces, no text inside (translations).
   * Made as SVG in-house (or adapted from a CC0 set such as Open Peeps/Humaaans), **with the licence recorded** next to each file;
     never images taken from the web or generated without checking rights.
   * At most ~12 illustrations, all in one folder (`app/assets/illustrations/` and the same files for the admin web app).
5. **Words.** Short, warm, specific: "Riley's Music is ready", "Nina added 3 songs to the Jam", "Saved. It's on your server now."
   One sentence of help under anything new (R-19).

## 3. The places where it matters most

| Place | What a person should feel | How |
|-------|---------------------------|-----|
| Setup wizard (`15` §2) | "This is easy and it's mine" | Illustrations per page, the server colour chosen on page 2 used from then on, the cover mosaic on "All set" |
| App welcome (A1) | "This is a music app, not a tool" | Cover wall background, moving logo bars, two big buttons |
| Join (A2) | "My friend invited me" | The server's colour and name, the inviter's name and avatar |
| Home | "It knows me" | Big covers, the person's own mixes (P4-01), greeting by time of day (exists) |
| Full player | "Immersive" | Artwork-coloured background, large cover, lyrics one swipe away |
| Jam | "We're together" | Everyone's avatars around the cover, "added by" on each song, the shared song colour |
| Year in Music | "That's me" | A designed, shareable story-style sequence (owner asked earlier for a designed Wrapped look) |
| Empty and error states | "Nothing is broken, here's what to do" | An illustration + one sentence + one button |

## 4. Rules that keep it fast and accessible

* Animations run only while visible, are cheap (no blur/shader animation on every frame; the stuck-spinner cost in `01` E7 is the
  example to avoid), and stop when the battery saver is on.
* Text on artwork always has a scrim for contrast (`07` §10 contrast check).
* Dark theme is the default; the light theme gets the same care.
* The admin web app uses the same tokens (generated CSS, as the old admin did) and the same illustrations.

## 5. Work

* **P1-10** removes letter tiles; **P1-12** adds the accessibility rules.
* A design task in **P3-06** (wizard) and **P2-10** (app welcome and join) draws the screens in the tokens with the illustrations
  before building them; the owner reviews the drawings (static images in the PR) before code.
* **P4-05** designs the Year in Music sequence; **P4-02/P4-10** the Jam screen.
* The logo and name come with **P5-05**, when the owner wants.
