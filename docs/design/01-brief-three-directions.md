# Design 01 — The brief for three directions (2026-10-24)

The owner asked for a design of all pages, drawn before it is coded, "with multiple versions". This is the brief each version is drawn from, so the three can be compared fairly. Inputs: `../16-look-and-feel.md` (personality, sources of life, words), `../../app/lib/design/tokens.dart` (today's tokens: accent `#19E68C`, dark background `#0E0E10`, Figtree), `00-screen-inventory.md` (the screens and their states), `../31` to `../34` (what each state says), `../11` ADR-R42 (layout classes, D-pad, right-to-left, text scale).

## What each direction draws

The four **anchor** screens of the inventory: **S-10 Home**, **S-31 Now playing** (with S-30 the mini player), **S-12 Search results with S-19 an Artist page** (one flow), **S-01 Welcome: find my server** with **S-71 Your server**. Each at three layout classes: **C** compact phone (360x800), **X** expanded browser (1280x800), **T** ten-foot TV (1920x1080). And, for the states that decide whether a design is honest, at least these:

| Screen | States that must be drawn |
|--------|---------------------------|
| Home | a new person ("Start with something"), a full Home, offline strip, "Can't reach your server." strip over a Home that still shows the library, loading skeleton |
| Now playing | playing; **waiting for the server** (the song is chosen, the server does not answer: the song stays, it says so in one plain sentence, nothing hops to the next song); cannot play (one sentence, a button that works); a song with two credited artists ("Aymane Haqqi, L'morphine", both tappable); another device is playing |
| Search + Artist | Top result with owned and catalogue rows looking the same; the library answering first and the catalogue second; no results ("lmorphine chrono" must not dead-end: say what was tried and offer the nearest); an artist page with a new release (EP out today) |
| Welcome / Your server | nothing found nearby, found one ("Riley's Music"), found two, scanning a QR, a typed address under "Other ways to connect", **another server answers at this address**, Your server with "Home", "Away" and a typed address, one of them not answering |

## Rules every direction obeys (the same, so the comparison is about design, not about rules)

1. **Real data, no lorem ipsum.** Use real artists and albums the owner plays (Pink Floyd, Radiohead, Paul Kalkbrenner, Fairouz, L'morphine, Daft Punk), real durations and plain sentences from the tables. Covers are drawn as generated colour artwork (gradients and simple shapes made in CSS or SVG, never a stolen image and never a letter tile; docs/16 says letter tiles are a bug).
2. **Tokens, not colours.** Everything derives from CSS custom properties named like `tokens.dart` (`--bg`, `--surface`, `--surface-high`, `--outline`, `--on-bg`, `--on-bg-muted`, `--accent`, `--danger`, `--warning`, radii, spacing, motion). A direction may change the values and add tokens; it names every one. Dark is the default and the light theme is drawn for at least Home.
3. **No text inside pictures; no text only in colour.** Everything survives text at **200 %** (one page of each screen is shown at 200 %) and **right-to-left** (a switch on every page flips `dir="rtl"` and the layout mirrors; Arabic sample strings: "فيروز", "الرئيسية").
4. **Touch targets 48 px or more on C; a visible focus ring on every control on X and T**, drawn (not described); the TV frames show where the D-pad focus is and how it moves. Nothing needs hover or a long press.
5. **Contrast**: body text 4.5:1 or better, large text 3:1, checked (state the pairs). Text on artwork has a scrim.
6. **Words from the tables and from `../16`.** Plain, warm, specific. "Can't reach your server." not "Connection failed". Listener screens never say IP address, port, token, Subsonic, sync or transcode.
7. **Familiar.** Spotify-class patterns are fine (bottom tabs on C, a side rail on X, rows of shelves on T); no Spotify (or any other product) name, logo, trade dress or copied artwork.
8. **Motion** is described in a short list (what moves, how long, what it does under "remove animations") and shown only where it is cheap to show. No animation that would cost frames on a mid phone (docs/16 §4).

## What each direction hands back

One self-contained HTML file, `anchors.html`, no external files except Google Fonts (Figtree or the direction's own, with a licence that allows it), with:

* a top bar to switch **screen, state, class (C/X/T), theme (dark/light), text size (100/200 %), direction of writing (ltr/rtl)**;
* the frames drawn at true size (C 360x800, X 1280x800, T 1920x1080 scaled to fit the window with a visible label of the scale);
* a "Tokens" page: every colour, radius, spacing, type size and motion value used, with the contrast pairs;
* a "Why" page of at most 12 lines: the idea in one sentence, what it is good at, what it is bad at, what it costs to build in Flutter (named widgets), and one thing the other two directions probably do better.

## The three directions (different on purpose)

* **A: Cover-led.** The music is the art (`../16` §2): large covers, colour taken from the artwork behind headers and the player, gradients, generous motion. Closest to the app's current spirit and to Spotify and Plexamp.
* **B: Quiet editorial.** Type-led and calm: strong hierarchy, small covers, neutral surfaces, the accent used rarely and meaning something ("this is playing", "this needs you"). Reads well in sunlight, at 200 % text and from a sofa; the easiest to make consistent on a TV.
* **C: Warm home.** The server is a place: its name and colour are the identity ("Riley's Music"), rounded cards, a few illustrations (docs/16 §2.4, simple shapes, no text), friendly first-run, made for the person who has never run a server. Closest to what Plex does for ordinary people.

## How the choice is made

By a short matrix (`02-direction-choice.md`) against: honest states (does "waiting for the server" look different from "broken"?), the TV (focus, distance, no touch), 200 % text and right-to-left, cost in Flutter, speed (frames, memory), how personal it feels, and the first-run of a person who does not know what a server is. The choice and the reasons go in the decision log; the other two are kept, because parts of them will be borrowed.
