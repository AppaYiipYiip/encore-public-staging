# Design 02 — Which direction (2026-10-24, decided by the advisor model after looking at the three drawings)

> **Closed by the owner, 2026-10-24: only the cover-led direction (A) continues, in Spotify-like colours and layout. The other two drawings are dropped and removed from the repository (they stay in the git history); nothing below about borrowing from them is to be followed any more.** What survives from them is simply part of A's specification: the state marks (a song that waits, cannot play or is offline is told apart by words and shapes, never by colour alone), the rules for text at 200 % and right-to-left, and the friendly personality of the first-run and connection screens. The matrix is kept only as the record of how the choice was made.

Inputs: the three files in `directions/` (open one in a browser; every view has a link, for example `a-cover-led.html#screen=np&state=waiting&cls=C&theme=dark&text=100&dir=ltr`; the top bar switches screen, state, class C/X/T, theme, text size and writing direction; each has a Tokens page and a Why page), the brief (`01`), the owner's words and `../16`. Each file was drawn by a separate agent from the same brief and checked in a headless browser (tag balance, 200 % text, right-to-left, light and dark, contrast pairs computed by the file itself). The drawings use invented song lengths and some sentences that are not in the state tables; each file marks the wording that is new.

## The matrix (brief `01`, "How the choice is made")

| Criterion | **A: Cover-led** | **B: Quiet editorial** | **C: Warm home** |
|-----------|------------------|------------------------|------------------|
| **Honest states** (does waiting look different from broken?) | Yes, and it survives greyscale (checked by the agent): *waiting* keeps the place (2:14), Next unchanged, a cloud icon, a secondary "Try again", an amber ring on play; *broken* dims the cover, shows 0:00, a warning triangle and a filled "Try again". One strip sentence from `31`, no second strip | **Best.** Waiting = amber dashed ring with a clock hand, dashed amber scrubber, hollow thumb, the song and its place stay; broken = red square-cross, hatched scrubber at 0:00, retry; offline = neutral grey plus the words "Not downloaded" and a check on downloaded songs, so grey is never the only cue | Yes: amber halo and an in-player sentence ("Waiting for your server. This song starts again where it stopped."); broken has its own sentence and a button. Colour carries more of it than in B |
| **The TV** | Cover colour fills the backdrop, a hero with Play and Save, shelves, focus ring with a 1.06 lift, the D-pad legend drawn | Left rail, big type, numbered D-pad order badges on every tile, a focus ring; the most readable from a sofa | Shelves with a ring and halo, a key legend; top bar navigation. Sign-in on a TV by a code shown on the TV |
| **200 % text and right-to-left** | The weakest of the three (stated by its own agent): the cover shrinks first; the shortcut grid becomes one column; a few labels stop at 130 to 150 %; two panels scroll | **Best**: the agent's check ran over all 66 frames in both directions, at 100 and 200 %, dark and light: no touch target under 48 px, no horizontal overflow; contrast 7 to 16:1 | Middle: display sizes stop at 150 %, everything else doubles; the Arabic is a handful of strings |
| **Cost to build in Flutter** | Medium to high: colour from the cover (`PaletteGenerator` in an isolate, cached), an inherited tint, `Hero`, `SliverAppBar` | **Low**: stock `NavigationBar`/`NavigationRail`, hairline dividers, one font family | Medium: restyle of the tokens, a per-server accent, eight SVG illustrations |
| **Speed** (frames, memory) | Only the cover wall and the equaliser bars loop (transforms only); a palette per cover, once | Nothing special; no blur, no per-frame work | Nothing special |
| **How personal it feels** | **Highest**: the music is the interface (`../16` §2.1, §2.2) | Lowest: its own agent calls it "the least alive of the three" | High, but about the *server*, not the music |
| **First run of a person who has never heard of a server** | Good (found one, found two, QR, typed address under "Other ways to connect") | Good | **Best**: the server is a place with a name and a colour, written for that person |

## Decision (ADR-R43; it is in `../11` as ADR-R43)

**Direction A is the base for the whole app.** It is the only one that matches `../16` ("the music is the art", warm, alive, not "server admin") and the owner's requests ("Spotify-class", "make it more alive"). The other two each break one of those on their own terms: B is quiet by design, C puts the server's status ("Riley's Music · Working · 4,213 songs") on the listener's Home, which is the admin feel `../16` rules out.

**What is borrowed, and where** (named, not blended):

| From | What | Where it applies |
|------|------|------------------|
| **B** | The **state marks**: waiting = amber dashed scrubber and a hollow thumb; cannot play = red hatched scrubber at 0:00 and a retry; offline = grey plus the words "Not downloaded" and a check on downloaded songs | **Every** screen that plays or lists songs (S-30, S-31, S-33 and every list): colour is never the only cue |
| **B** | The **200 % and right-to-left rules** (what scales, what is capped and why, nothing clipped, nothing overlapping), and numbered **D-pad order** on the TV | Every screen |
| **C** | **First run and identity**: the server as a place with a name and a colour, the friendly first-run writing, the illustrations of `../16` §2.4 | **Only** Welcome (S-01), Join (S-02), Sign in (S-03, S-04), Your server (S-71) and the invitation screens (S-51). **Never on Home or the player** |
| **A, with Spotify's arrangement where a screen exists there** | Everything else: Home, Search, Artist, Album, Playlist, Library, **Now playing (exactly Spotify's mobile arrangement, `03` row 9)**, Lyrics, Queue, Jam, Year in Music. Familiar screens are copied, not improved | |

## Two things the drawings slipped in, settled here

1. **Navigation: three tabs** (Home, Search, Your Library), as the app has today. A and C drew a fourth, **People**; B kept three. A fourth tab is a change to what the app *is*, and what would sit in it (friends' activity) is not built and is in `../tasks/P6-later.md`. People and Jam stay where they are (the Jam button and the friends shelf on Home, the person's menu), and the fourth entry is drawn only when friend activity exists. The TV top bar and the browser rail show the same three. *Revisit when friend activity ships.*
2. **One pattern for "the server does not answer"**, so that the design, `../33` PB-F7 and the app say the same: **the same thin strip everywhere**, with the one offline sentence of `../31` CN-1 and a cross to dismiss it (`../31` CN-14, after 4 s; D-45 on 2026-10-31 replaced the words "Can't reach your server." and the Try again button), at the top of every screen including the full Now playing; the mini player shows the song in *waiting*, and on the full player the scrubber has B's dashed unplayed part and a hollow thumb, the song, its place and Next unchanged. *(Revised after the owner's review, `03` row 9: an earlier version of this paragraph put a status row inside the full player, which Spotify does not have.)* The G-1 build also says "Waiting for your server." once as a notice when the wait starts. `../33` PB-F7 says so.

## Found while drawing (all three agents agreed)

* **The light theme in `app/lib/design/tokens.dart` fails contrast.** The accent `#0BA862` with white text is 3.1:1; the light warning (`#B54708`) and danger (`#D92D20`) pills are about 4.2:1 on their tints. Direction A's values that pass: accent `#07703F`, danger `#BC2318`, warning `#A63F06`. This is a defect today, whichever direction wins: a small pull request changes the three tokens and the light screen pictures.
* **Wording that is not in the state tables** (each file marks it "new wording"): "Waiting for your server." and its body line, "No servers on this Wi-Fi.", "Use an invite link or a QR code from the person who runs your server.", "Nothing was sent to it.", "Still looking in the catalogue…", "Not here yet? Ask your server to get it.", the TV "use a code from your phone" text, a handful of Arabic sentences. These go to the owner in plain words before they are built; the Arabic needs a native reader (`../tasks/P6-later.md`).
* **Data that is invented in the drawings**: the song lengths of the single and the EP (the owner's screenshot gave no times), several track lists. Never copied into the app.
* **"From Spotify or YouTube Music"** appears on Bring your music (S-06) as in the story; it names two products and is the one place where rule 7 of the brief is read loosely. Easy to drop.

## Next

1. Draw the rest of `00-screen-inventory.md` in direction A (Library, Album, Playlist, Lyrics, Queue, Song menu, Settings, Import, Jam, Year in Music, Join, the browser pages), each with its states, at C, X and T. One file per group, in `directions/` or `screens/`.
2. Show the owner the choice and the three drawings (a private page), with the reasons above in his words. Nothing is coded before the owner has had the chance to say no.
3. Code, screen by screen, **golden pictures first** (text 1.0 and 2.0, left-to-right and right-to-left, dark and light), then the screen (ADR-R41 T6). The first three: the light tokens, the state marks in the player, then Home.
