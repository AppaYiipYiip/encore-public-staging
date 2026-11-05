# The design records of 24 to 30 Oct 2026 (history, NOT instructions)

The brief for the three directions, the choice of direction, the owner's review of the drawings, and the review of every drawn screen against what was built (**the baseline of the app pass: its "Built" column has not been edited since 30 Oct 2026**). Every old file name starts a section. What is true now is in `docs/design/00-screen-inventory.md` and the drawings in `docs/design/directions/`.


| Old file | Section |
|----------|---------|
| `01-brief-three-directions.md` | [design-01-brief](#design-01-brief) |
| `02-direction-choice.md` | [design-02-direction-choice](#design-02-direction-choice) |
| `design-03-owner-review-2026-10-24.md` | [design-03-owner-review-2026-10-24](#design-03-owner-review-2026-10-24) |
| `design-04-review-2026-10-30.md` | [design-04-review-2026-10-30](#design-04-review-2026-10-30) |

---

<a id="design-01-brief"></a>
## design-01-brief · 01-brief-three-directions.md

**Design 01 — The brief for three directions (2026-10-24)**

### Design 01 — The brief for three directions (2026-10-24)

The owner asked for a design of all pages, drawn before it is coded, "with multiple versions". This is the brief each version is drawn from, so the three can be compared fairly. Inputs: `../16-look-and-feel.md` (personality, sources of life, words), `../../app/lib/design/tokens.dart` (today's tokens: accent `#19E68C`, dark background `#0E0E10`, Figtree), `00-screen-inventory.md` (the screens and their states), `../31` to `../34` (what each state says), `../11` ADR-R42 (layout classes, D-pad, right-to-left, text scale).

#### What each direction draws

The four **anchor** screens of the inventory: **S-10 Home**, **S-31 Now playing** (with S-30 the mini player), **S-12 Search results with S-19 an Artist page** (one flow), **S-01 Welcome: find my server** with **S-71 Your server**. Each at three layout classes: **C** compact phone (360x800), **X** expanded browser (1280x800), **T** ten-foot TV (1920x1080). And, for the states that decide whether a design is honest, at least these:

| Screen | States that must be drawn |
|--------|---------------------------|
| Home | a new person ("Start with something"), a full Home, offline strip, "Can't reach your server." strip over a Home that still shows the library, loading skeleton |
| Now playing | playing; **waiting for the server** (the song is chosen, the server does not answer: the song stays, it says so in one plain sentence, nothing hops to the next song); cannot play (one sentence, a button that works); a song with two credited artists ("Aymane Haqqi, L'morphine", both tappable); another device is playing |
| Search + Artist | Top result with owned and catalogue rows looking the same; the library answering first and the catalogue second; no results ("lmorphine chrono" must not dead-end: say what was tried and offer the nearest); an artist page with a new release (EP out today) |
| Welcome / Your server | nothing found nearby, found one ("Riley's Music"), found two, scanning a QR, a typed address under "Other ways to connect", **another server answers at this address**, Your server with "Home", "Away" and a typed address, one of them not answering |

#### Rules every direction obeys (the same, so the comparison is about design, not about rules)

1. **Real data, no lorem ipsum.** Use real artists and albums the owner plays (Pink Floyd, Radiohead, Paul Kalkbrenner, Fairouz, L'morphine, Daft Punk), real durations and plain sentences from the tables. Covers are drawn as generated colour artwork (gradients and simple shapes made in CSS or SVG, never a stolen image and never a letter tile; docs/16 says letter tiles are a bug).
2. **Tokens, not colours.** Everything derives from CSS custom properties named like `tokens.dart` (`--bg`, `--surface`, `--surface-high`, `--outline`, `--on-bg`, `--on-bg-muted`, `--accent`, `--danger`, `--warning`, radii, spacing, motion). A direction may change the values and add tokens; it names every one. Dark is the default and the light theme is drawn for at least Home.
3. **No text inside pictures; no text only in colour.** Everything survives text at **200 %** (one page of each screen is shown at 200 %) and **right-to-left** (a switch on every page flips `dir="rtl"` and the layout mirrors; Arabic sample strings: "فيروز", "الرئيسية").
4. **Touch targets 48 px or more on C; a visible focus ring on every control on X and T**, drawn (not described); the TV frames show where the D-pad focus is and how it moves. Nothing needs hover or a long press.
5. **Contrast**: body text 4.5:1 or better, large text 3:1, checked (state the pairs). Text on artwork has a scrim.
6. **Words from the tables and from `../16`.** Plain, warm, specific. "Can't reach your server." not "Connection failed". Listener screens never say IP address, port, token, Subsonic, sync or transcode.
7. **Familiar.** Spotify-class patterns are fine (bottom tabs on C, a side rail on X, rows of shelves on T); no Spotify (or any other product) name, logo, trade dress or copied artwork.
8. **Motion** is described in a short list (what moves, how long, what it does under "remove animations") and shown only where it is cheap to show. No animation that would cost frames on a mid phone (docs/16 §4).

#### What each direction hands back

One self-contained HTML file, `anchors.html`, no external files except Google Fonts (Figtree or the direction's own, with a licence that allows it), with:

* a top bar to switch **screen, state, class (C/X/T), theme (dark/light), text size (100/200 %), direction of writing (ltr/rtl)**;
* the frames drawn at true size (C 360x800, X 1280x800, T 1920x1080 scaled to fit the window with a visible label of the scale);
* a "Tokens" page: every colour, radius, spacing, type size and motion value used, with the contrast pairs;
* a "Why" page of at most 12 lines: the idea in one sentence, what it is good at, what it is bad at, what it costs to build in Flutter (named widgets), and one thing the other two directions probably do better.

#### The three directions (different on purpose)

* **A: Cover-led.** The music is the art (`../16` §2): large covers, colour taken from the artwork behind headers and the player, gradients, generous motion. Closest to the app's current spirit and to Spotify and Plexamp.
* **B: Quiet editorial.** Type-led and calm: strong hierarchy, small covers, neutral surfaces, the accent used rarely and meaning something ("this is playing", "this needs you"). Reads well in sunlight, at 200 % text and from a sofa; the easiest to make consistent on a TV.
* **C: Warm home.** The server is a place: its name and colour are the identity ("Riley's Music"), rounded cards, a few illustrations (docs/16 §2.4, simple shapes, no text), friendly first-run, made for the person who has never run a server. Closest to what Plex does for ordinary people.

#### How the choice is made

By a short matrix (`02-direction-choice.md`) against: honest states (does "waiting for the server" look different from "broken"?), the TV (focus, distance, no touch), 200 % text and right-to-left, cost in Flutter, speed (frames, memory), how personal it feels, and the first-run of a person who does not know what a server is. The choice and the reasons go in the decision log; the other two are kept, because parts of them will be borrowed.

---

<a id="design-02-direction-choice"></a>
## design-02-direction-choice · 02-direction-choice.md

**Design 02 — Which direction (2026-10-24, decided by the advisor model after looking at the three drawings)**

### Design 02 — Which direction (2026-10-24, decided by the advisor model after looking at the three drawings)

> **Closed by the owner, 2026-10-24: only the cover-led direction (A) continues, in Spotify-like colours and layout. The other two drawings are dropped and removed from the repository (they stay in the git history); nothing below about borrowing from them is to be followed any more.** What survives from them is simply part of A's specification: the state marks (a song that waits, cannot play or is offline is told apart by words and shapes, never by colour alone), the rules for text at 200 % and right-to-left, and the friendly personality of the first-run and connection screens. The matrix is kept only as the record of how the choice was made.

Inputs: the three files in `directions/` (open one in a browser; every view has a link, for example `a-cover-led.html#screen=np&state=waiting&cls=C&theme=dark&text=100&dir=ltr`; the top bar switches screen, state, class C/X/T, theme, text size and writing direction; each has a Tokens page and a Why page), the brief (`01`), the owner's words and `../16`. Each file was drawn by a separate agent from the same brief and checked in a headless browser (tag balance, 200 % text, right-to-left, light and dark, contrast pairs computed by the file itself). The drawings use invented song lengths and some sentences that are not in the state tables; each file marks the wording that is new.

#### The matrix (brief `01`, "How the choice is made")

| Criterion | **A: Cover-led** | **B: Quiet editorial** | **C: Warm home** |
|-----------|------------------|------------------------|------------------|
| **Honest states** (does waiting look different from broken?) | Yes, and it survives greyscale (checked by the agent): *waiting* keeps the place (2:14), Next unchanged, a cloud icon, a secondary "Try again", an amber ring on play; *broken* dims the cover, shows 0:00, a warning triangle and a filled "Try again". One strip sentence from `31`, no second strip | **Best.** Waiting = amber dashed ring with a clock hand, dashed amber scrubber, hollow thumb, the song and its place stay; broken = red square-cross, hatched scrubber at 0:00, retry; offline = neutral grey plus the words "Not downloaded" and a check on downloaded songs, so grey is never the only cue | Yes: amber halo and an in-player sentence ("Waiting for your server. This song starts again where it stopped."); broken has its own sentence and a button. Colour carries more of it than in B |
| **The TV** | Cover colour fills the backdrop, a hero with Play and Save, shelves, focus ring with a 1.06 lift, the D-pad legend drawn | Left rail, big type, numbered D-pad order badges on every tile, a focus ring; the most readable from a sofa | Shelves with a ring and halo, a key legend; top bar navigation. Sign-in on a TV by a code shown on the TV |
| **200 % text and right-to-left** | The weakest of the three (stated by its own agent): the cover shrinks first; the shortcut grid becomes one column; a few labels stop at 130 to 150 %; two panels scroll | **Best**: the agent's check ran over all 66 frames in both directions, at 100 and 200 %, dark and light: no touch target under 48 px, no horizontal overflow; contrast 7 to 16:1 | Middle: display sizes stop at 150 %, everything else doubles; the Arabic is a handful of strings |
| **Cost to build in Flutter** | Medium to high: colour from the cover (`PaletteGenerator` in an isolate, cached), an inherited tint, `Hero`, `SliverAppBar` | **Low**: stock `NavigationBar`/`NavigationRail`, hairline dividers, one font family | Medium: restyle of the tokens, a per-server accent, eight SVG illustrations |
| **Speed** (frames, memory) | Only the cover wall and the equaliser bars loop (transforms only); a palette per cover, once | Nothing special; no blur, no per-frame work | Nothing special |
| **How personal it feels** | **Highest**: the music is the interface (`../16` §2.1, §2.2) | Lowest: its own agent calls it "the least alive of the three" | High, but about the *server*, not the music |
| **First run of a person who has never heard of a server** | Good (found one, found two, QR, typed address under "Other ways to connect") | Good | **Best**: the server is a place with a name and a colour, written for that person |

#### Decision (ADR-R43; it is in `../11` as ADR-R43)

**Direction A is the base for the whole app.** It is the only one that matches `../16` ("the music is the art", warm, alive, not "server admin") and the owner's requests ("Spotify-class", "make it more alive"). The other two each break one of those on their own terms: B is quiet by design, C puts the server's status ("Riley's Music · Working · 4,213 songs") on the listener's Home, which is the admin feel `../16` rules out.

**What is borrowed, and where** (named, not blended):

| From | What | Where it applies |
|------|------|------------------|
| **B** | The **state marks**: waiting = amber dashed scrubber and a hollow thumb; cannot play = red hatched scrubber at 0:00 and a retry; offline = grey plus the words "Not downloaded" and a check on downloaded songs | **Every** screen that plays or lists songs (S-30, S-31, S-33 and every list): colour is never the only cue |
| **B** | The **200 % and right-to-left rules** (what scales, what is capped and why, nothing clipped, nothing overlapping), and numbered **D-pad order** on the TV | Every screen |
| **C** | **First run and identity**: the server as a place with a name and a colour, the friendly first-run writing, the illustrations of `../16` §2.4 | **Only** Welcome (S-01), Join (S-02), Sign in (S-03, S-04), Your server (S-71) and the invitation screens (S-51). **Never on Home or the player** |
| **A, with Spotify's arrangement where a screen exists there** | Everything else: Home, Search, Artist, Album, Playlist, Library, **Now playing (exactly Spotify's mobile arrangement, `03` row 9)**, Lyrics, Queue, Jam, Year in Music. Familiar screens are copied, not improved | |

#### Two things the drawings slipped in, settled here

1. **Navigation: three tabs** (Home, Search, Your Library), as the app has today. A and C drew a fourth, **People**; B kept three. A fourth tab is a change to what the app *is*, and what would sit in it (friends' activity) is not built and is in `../tasks/P6-later.md`. People and Jam stay where they are (the Jam button and the friends shelf on Home, the person's menu), and the fourth entry is drawn only when friend activity exists. The TV top bar and the browser rail show the same three. *Revisit when friend activity ships.*
2. **One pattern for "the server does not answer"**, so that the design, `../33` PB-F7 and the app say the same: **the same thin strip everywhere**, with the one offline sentence of `../31` CN-1 and a cross to dismiss it (`../31` CN-14, after 4 s; D-45 on 2026-10-31 replaced the words "Can't reach your server." and the Try again button), at the top of every screen including the full Now playing; the mini player shows the song in *waiting*, and on the full player the scrubber has B's dashed unplayed part and a hollow thumb, the song, its place and Next unchanged. *(Revised after the owner's review, `03` row 9: an earlier version of this paragraph put a status row inside the full player, which Spotify does not have.)* The G-1 build also says "Waiting for your server." once as a notice when the wait starts. `../33` PB-F7 says so.

#### Found while drawing (all three agents agreed)

* **The light theme in `app/lib/design/tokens.dart` fails contrast.** The accent `#0BA862` with white text is 3.1:1; the light warning (`#B54708`) and danger (`#D92D20`) pills are about 4.2:1 on their tints. Direction A's values that pass: accent `#07703F`, danger `#BC2318`, warning `#A63F06`. This is a defect today, whichever direction wins: a small pull request changes the three tokens and the light screen pictures.
* **Wording that is not in the state tables** (each file marks it "new wording"): "Waiting for your server." and its body line, "No servers on this Wi-Fi.", "Use an invite link or a QR code from the person who runs your server.", "Nothing was sent to it.", "Still looking in the catalogue…", "Not here yet? Ask your server to get it.", the TV "use a code from your phone" text, a handful of Arabic sentences. These go to the owner in plain words before they are built; the Arabic needs a native reader (`../tasks/P6-later.md`).
* **Data that is invented in the drawings**: the song lengths of the single and the EP (the owner's screenshot gave no times), several track lists. Never copied into the app.
* **"From Spotify or YouTube Music"** appears on Bring your music (S-06) as in the story; it names two products and is the one place where rule 7 of the brief is read loosely. Easy to drop.

#### Next

**Status 2026-11-01.** Items 1 and 2 are done: the five drawing files exist, and the owner was shown them on a private page (now `directions/index.html`), chose on 2026-10-24 and answered again on 2026-10-31 (D-43). Item 3 became the rule of D-43: the built screen is the reference, and a page is drawn only when it is new and about to be built.

1. Draw the rest of `00-screen-inventory.md` in direction A (Library, Album, Playlist, Lyrics, Queue, Song menu, Settings, Import, Jam, Year in Music, Join, the browser pages), each with its states, at C, X and T. One file per group, in `directions/` or `screens/`.
2. Show the owner the choice and the three drawings (a private page), with the reasons above in his words. Nothing is coded before the owner has had the chance to say no.
3. Code, screen by screen, **golden pictures first** (text 1.0 and 2.0, left-to-right and right-to-left, dark and light), then the screen (ADR-R41 T6). The first three: the light tokens, the state marks in the player, then Home.

---

<a id="design-03-owner-review-2026-10-24"></a>
## design-03-owner-review-2026-10-24 · design-03-owner-review-2026-10-24.md

**Design 03 — The owner's review of the three drawings (2026-10-24), one verdict per point**

### Design 03 — The owner's review of the three drawings (2026-10-24), one verdict per point

The owner looked at the drawn directions (`directions/`, shown on a private page) and said what he likes and what he does not. This is each point, the verdict (decided with the advisor model) and where it lands. Rule that comes out of it: **familiar screens copy Spotify's arrangement exactly and are not "improved"; personality belongs on the welcome and first-run screens; nothing on screen shows what the listener does not need to know.**

| # | The owner said | Verdict | Where it lands |
|---|----------------|---------|----------------|
| 1 | Home, Search and Library at the bottom is the best option; three buttons keep it familiar and simple | **Confirmed.** Three tabs. People and Jam stay reachable from Home shortcuts and the profile menu | `02` (already), the drawings (the fourth tab is removed) |
| 2 | "In Spotify how do you add a friend?" | **In Spotify you *follow* somebody**: Search, then "Profiles"; or open their profile link or QR code (their profile's ⋯ menu, Share); or find friends through Facebook. "Friend Activity" (what friends play) is mostly the desktop app ([guides read 2026-10-24](https://www.soundguys.com/how-to-add-friends-on-spotify-101567/), [another](https://www.technobezz.com/how-to-follow-friends-on-spotify)). **For Encore:** people on the *same server* are already there (nobody adds anybody); anybody else arrives by **invitation link or QR** (already built); following a person on another server needs the server to have connecting with other servers switched on (point 5) | `00` S-51, `../03a` US-62/US-72 (unchanged), `../tasks/P4` P4-03 |
| 3 | "I'm not fully OK with some design elements, but I love the **Welcome / find my server** pages: they have personality" | **Kept as they are**, apart from the server's name (point 4). That personality (the server as a place with a name and a colour, a small illustration, plain friendly words) is used on **every first-run, connection and account screen**: Welcome, Join, Sign in, Sign in again, Your server, invitations, and the browser wizard and join page. It is *not* used on Home or the player | `02` borrow table, the redrawn Your server |
| 4 | "Why would I call a server that is not meant for one person by my name?" | **He is right.** A shared server is named for the household or the place: "Our music", "Home", "The flat". The wizard pre-fills "Our music" and shows two more examples; a person's name appears only in "invited by Riley" and in the greeting. The drawings' sample data is redone ("Our music", second server "The Flat") | `../15` page 2, A2 and the "ready" page, every drawing |
| 5 | "Not everyone would let their server talk to other servers; what does the UI do?" | **The UI follows the server's capabilities.** Anything that crosses servers (friends on other servers, a Jam with them, comparing tastes across servers) is shown **only when the server's `GET /info` `features` says it is on**, which is the Host's choice in the wizard ("Friends on other servers: allowed") and the admin page. When it is off there is **no empty placeholder, no greyed-out menu, no nagging**: the screen simply has no such thing. The listener never sees the switch; only the owner does, in the admin. Same rule for any later optional feature (a catalogue source, a quality tier) | `../11` ADR-R42 point 9, `00` (a "when the server allows" column in the inventory) |
| 6 | "The buttons **Check addresses** and **Add an address** on Your server: my least favourite, no personality" | **Redesigned** with the Welcome pages' personality: a hero card with the server's name, colour and a small illustration and **one sentence of status** ("Working. You are at home."); a section **"How this phone reaches it"** with two plain rows, **At home** and **Away from home** (the addresses the server itself told the phone; each says in words whether it answers); **one** button, **"Test the connection"**, that answers in a sentence ("Your server answered in 0.2 seconds." / "Nothing answered at home, but away from home works."); typed addresses live under **"Other ways to connect"**, collapsed, as on Welcome. "Check addresses" and "Add an address" disappear from the top level. This also closes `../31` O-8 (the addresses the server told the phone are visible and can be left out). **Since 2026-10-30 there is no "Test the connection" button (F40):** the app checks each address by itself when the page opens and shows its answer beside it; the frame was not redrawn (D-43) | `00` S-71, the redrawn frame, `../31` O-8 |
| 7 | "In Search and Artist I don't like the yellow **owned / catalogue** box. How does Spotify say already liked or already downloaded? With icons. Do we even need the listener to know that?" | **No: the listener does not need to know what is on the server.** The drawing broke the story's own rule (`../03a` US-10: owned and catalogue songs look the same, nothing says "not in your library"). The only marks on a song row are Spotify's: **downloaded** (the green arrow), **liked** (the heart), **explicit** (the E), and, offline, B's grey **plus the words "Not downloaded"** so colour is never the only cue. A song that is still being fetched shows a small spinner and no words about servers | `00` S-12/S-19, `02`, the redrawn frames |
| 8 | "With several users on one server, a **comparison of listening habits** would be nice: you both like X, your favourite genre is Y. Also between friends. But sometimes I don't want to share what I listen to: it should be opt-in" | **Recorded now, built later.** Story **US-65**, task **P4-17**, screen **S-54 Taste match**. **Off by default. Both people must opt in before either sees anything, either can withdraw at any moment (the comparison disappears at once), listening marked "private" is never counted, and a person who has not opted in does not even appear as comparable.** The server computes it (ADR-R42; nothing is sent to the other phone but the result), between people on the same server first, across servers only when connecting with other servers is on. The familiar pattern is Spotify's **Blend** (a taste match and a shared playlist). It is a **later** feature: the design draws the screen and the settings switch; no code until the owner has used the app daily | `../03a` US-65, `../tasks/P4` P4-17, `00` S-54, `../21` (privacy) |
| 9 | "In **Now playing** I don't like the queue button, the messaging button, and so on. Copy Spotify, don't try to improve something. Keep the app familiar: Spotify is the most common music app" | **Now playing copies Spotify's mobile arrangement exactly**: top, a down chevron, "Playing from …" and a ⋯ menu; a large cover; the title and artist on the left and the heart (save) on the right; the scrubber with times; **shuffle, previous, a big play button, next, repeat**; a bottom row with the **device** icon on the left and the small **share** and **queue** icons on the right (Spotify has that small queue icon; what he disliked was A's "Next: …" card and the lyrics icon); **lyrics appear as a card when you scroll down**. Nothing else. The "server does not answer" state is the **same thin strip** as everywhere ("Can't reach your server." with Try again, `../31` CN-14; since 2026-10-31 the words are the one offline sentence of D-45 and the strip has a cross, no Try again) at the top, with B's dashed scrubber and hollow thumb; the song, its place and Next stay as they are. **This replaces the "status row inside the full player" of `02`** (Spotify has no such row), and `../33` PB-F7 is corrected. **Since 2026-10-30 the app has neither the device icon (D-28) nor the share icon, and no playback speed in the ⋯ menu (D-23); the built screen is the reference (D-43).** Sources for Spotify's layout: [Spotify's own page](https://support.spotify.com/in-en/article/now-playing/) (save, shuffle, repeat, play queue, Connect, ⋯) and the owner's phone; the exact arrangement is to be checked against it before it is built | `00` S-31, `02`, `../33` PB-F7, the redrawn frame |
| 10 | "Check with your advisor often. Continue." | Done and continuing | — |

#### What stays open

* The owner "is not fully OK with some design elements" without saying which: after the redraw he is shown the revised anchors again, and nothing is coded before that. If it was another drawing's Welcome that he liked, the answer to "which one?" decides nothing about the build (the Welcome of C's treatment is the one kept).
* Spotify's Now Playing has changed layout several times; the arrangement above is the common one in the support page and the search results, and the owner's own phone is the reference for the details (where the lyrics card starts, whether the device icon shows only when a device is nearby).

#### Second round (2026-10-24, later): what else is missing, decided by the advisor model because the owner was away

The owner: *"there are so many things we have not thought of: changing the profile picture; how the queue shows a recommendation that was not in the original; how the shuffle button shows smart shuffle; how are the recommendations going in the backend; notifications are not designed, do not bombard the phone, rarely or never; design the server side of the UI too, installation and everything."* And: *"do not wait for me, let the advisor decide."*

| # | Question | Decision | Where it lands |
|---|----------|----------|----------------|
| 1 | The queue and a recommended song; shuffle and Smart Shuffle | **Copy Spotify** ([Smart Shuffle](https://support.spotify.com/us/article/smart-shuffle/), Autoplay). Shuffle is a **three-state button**: off, shuffle, Smart Shuffle (shuffle with a small sparkle). The queue has **sections whose header words say where the songs come from** ("Next in queue" for what the person added, "Next from <playlist>", then a recommended section); a **recommended song carries a small sparkle** and one tap removes it. The header words tell the person, the sparkle is secondary. None of this exists unless the server has recommendations on (the capabilities rule, ADR-R42 point 8): drawn once, marked "later" | `00` S-31, S-33 |
| 2 | How are the recommendations going? | **Designed (`../20`), not built in the new server**: it is task P4-01, after the core. The old stack's engine is in `server/legacy`; the new one needs every play on a song ref (P2) and the catalogue on the server (P2-12). Smart Shuffle, autoplay, "Made for you" rows and song radio all wait for it, so the drawings show them as later | `../tasks/P4` P4-01 (unchanged) |
| 3 | Notifications | **None on the phone by default** (ADR-R44): the in-app bell (S-24) is the channel for new releases, an invitation used, an import finished. Settings > Notifications holds at most two opt-in phone categories, both off, one sentence each ("Jam invitations" is the obvious one); Android's permission is asked only when one is switched on. Code consequences: remove the permission prompt shown right after sign-in, and switch the background new-release check off by default (`background_sync` > `AlertsService`); check that the media controls still show with the permission denied (Android 13+ exempts media sessions) | ADR-R44, `../23` §4, `../tasks/P2` P2-15 |
| 4 | Changing the profile picture and the rest of "my account" | A new page **S-28 Your account / Edit profile**: picture, display name, change password, your devices, private listening, sign out, delete my account (later). The server stores a small avatar | `00` S-28 |
| 5 | The server's side of the UI | **Drawn too**: the installer wizard, the admin pages and the join page (W-01 to W-08) in a fourth batch of drawings after the app screens; the **terminal** (installer output and what each `encore` command prints) is text, written in `../15` §1 and §1b | `00` W-07, W-08, T-01, `../15` |
| 6 | "I don't know what else is missing" | **A gap pass by reading**: every story of `../03a` (US-01 to US-76) mapped to a screen, the four state tables mapped **by area** (connecting `31` to S-01, S-71, S-90; accounts and joining `32` to S-02 to S-08, S-28, S-73, W-01, W-03, W-05; playback `33` to S-30 to S-36, S-90; conflicts `34` to S-17, S-91), and Spotify's own settings sections walked (Account, Content and display, Privacy and social, Playback, Notifications, Devices, Data saving and offline, Media quality, About). What was missing is added to `00` (S-21 to S-28, W-07, W-08, T-01, the contents of S-72). A row-by-row check of `31` to `34` against the frames is still to do once the drawings are in (the drawings' frame labels carry the row ids, so `tools/check_rows.py`-style tooling can list rows that no frame shows) | `00` |

#### Third round (2026-10-24, evening): what the app-screen batch raised, decided by the advisor model

The drawing agent for the first-run, account and settings screens (172 frames, `directions/screens-first-run-and-settings.html`) listed seven conflicts between the documents and the code and some items "for the owner". Decided without the owner (standing authority, `feedback_advisor-decides-when-owner-away`):

| Conflict | Decision | Fixed in |
|----------|----------|----------|
| The sign-in code of Quick Connect: 6 digits (`32` AC-8) or 7 characters (the Welcome TV frame) | **6 digits everywhere**; the 5-minute life is the proposal in `32` JN-8 | the Welcome TV frame (corrections list below) |
| Password minimum: 10 (`15`) or 8 (`32`, the app, the server) | **8; the code wins** | `15` page 2 |
| "Normal" streaming and download quality: Opus 128 (`23`) or Opus 96 (the code) | **The code wins: Opus 96** | `23` §1 |
| Away-from-home streaming quality: one fixed profile (`23`) or the person's choice (the app) | **The person picks, as in Spotify**; the Host may cap away quality in the admin (W-07) and the app mentions a cap only when one exists | `23` §1 |
| Three notification switches in the app, at most two in ADR-R44 | **The drawings show the ADR's target (two, both off)**; the app is trimmed when the bell exists (PR for ADR-R44 says so; **decided again 2026-11-01, D-48 d: RC2, no code change before the QA rounds**) | the drawings |
| The strip's Try again: 48 px or 40 px | **48 px** (the touch-target rule) | the corrections list |
| Home and Privacy: separate pages (drawing) or one page "Privacy & your music" (app) | **Separate**, as drawn | the drawings |

Accepted as drafted: the refusal sentences, the 5 MB picture limit, "Invited by Riley" (as `15` A2), and the "Ask the owner of Our music to update the server." sentence without a person's name. **Owner-locked "Explicit songs"** stays because `explicit_ok` is per person in the server (`accounts.update_person`). **YouTube Music's third way in "Bring your music" (a data file) is marked "later"**: the server has no reader for such a file (`imports/readers.py` reads links and playlists only), and a drawing must not show a capability that does not exist.

##### Corrections the drawings still need (applied in one pass when the browser pages are drawn)

1. The Welcome TV frame shows a 7-character code: make it **6 digits**.
2. The strip's "Try again" in the direction-A anchors is 40 px: make it **48 px**.
3. "Bring your music": the YouTube Music **data file** way is drawn "later" (grey, one line), not as a working option.
4. The Notifications settings page shows **two** opt-in categories (both off), not three.

##### The library and browse screens (130 frames, `directions/screens-library-and-browse.html`): eight open points, all accepted by the advisor model

1. "Partly on the server" album: **no "Not in your library" heading** (it is a layout marker the rule forbids): all songs in order, the only sign is "11 of 14 songs" under the title, the song just tapped shows a plain spinner. 2. Your Library: the scope switch moves into the Sort sheet; the tab is "Downloads" as in Spotify; Liked Songs leads the Playlists list; offline the frame shows Playlists so the grey is visible (the app today opens on Downloads when offline: unchanged until the screen is built). 3. Offline rows: "Not downloaded" replaces the artist line, a downloaded song gets a check. 4. Album pages: the heart is "in your library", rows are plain two-line rows on a phone, numbered on browser and TV. 5. New playlist: full screen on a phone, a dialog in the browser; the "name is taken" check is new (server and app). 6. Import a playlist, Start a Jam, "Ask for it" and shared playlists show only when the server has them on; with none on, the + menu is just "New playlist". 7. A refused edit is parked with its reason (`34` CF-26, gap G-6) instead of vanishing. 8. Editing a playlist needs no drag or long press in the browser (Move up / Move down / Remove) and on the TV (OK picks up, Up/Down move, OK drops).

##### Lyrics, Devices, Jam, People, Year in Music, Import and the rest (164 frames, `directions/screens-player-together-and-more.html`): decided by the advisor model

* **People's names inside the app are fine** (Nina, Mia, "Hosted by Riley", "Added by Nina" on every Jam song): the rule is about the *server's* name, not about the people who use it.
* The invitation link carries a letter-and-digit code that is never shown to be typed; a code that **is** typed (Quick Connect, a Jam code) is six digits.
* Frames owned by the Home author that need the same touch-target fix (a 48 px scrubber hit area on a phone, a 48 px device button) go into the final consistency pass with the corrections list above; the profile menu opens from the avatar, which is drawn at the top left of Home (the drawn Home still shows it at the top right: to be corrected in the same pass).
* Not drawn on purpose: the Queue and the three-state shuffle (drawn with Now playing), the Notifications settings page (drawn with the settings), Friend activity and Taste match at the phone size only (both are "later").

#### Fourth group (2026-10-25): the server's browser pages, decided by the advisor model

The drawing agent for the browser pages (68 frames, `directions/screens-server-and-browser.html`: the installer wizard in 18 states, the admin's Home, People, Library, Away from home, Backups, Updates, Settings and Logs, the join page that an invitation link opens, and the web player) listed some conflicts and "owner decisions". Decided without the owner (standing authority, `feedback_advisor-decides-when-owner-away`); he can override any of them:

| Open point | Decision | Fixed in |
|------------|----------|----------|
| Three groupings of the admin pages (`15` §4, today's admin, the drawn rail) | **The drawn rail of eight is canonical**: Home, People, Library, Away from home, Backups, Updates, Settings, Logs | `15` §4 |
| Backups and Updates: one page or two | **Two**, as drawn (one has a restore command and no button, the other a version list and one command) | as drawn |
| The five server colours | **As drawn** | as drawn |
| New wording (for example "Music server is not answering.", "The update went back to 0.1.0.") and the brand names on the Host's pages (Tailscale, Soulseek, YouTube, yt-dlp) | **Accepted**: the Host needs the real names to act, as `15` and today's admin already do | as drawn |
| "Recommendations" drawn as a switch | **A grey "later" line with no switch**, as YouTube Music's data file is: a switch for a feature that does not exist breaks the rule that the screens follow what the server offers | the Settings frames |
| The installer's music folder shown as `/home/riley/Music` | **`/home/host/Music`**: a person's name does not belong in a server's page | `15` |
| `15` page 3 preselects "I don't have music files yet" but page 9 said "5,616 songs" | **The drawing is right**: page 9 now says "Ready for your first songs" and notes the other case | `15` |
| Used and expired invitation: two frames in the brief, one in the drawing | **One**: `IV-4` gives both the same sentence on purpose | as drawn |
| The admin's own sign-in page | **Not drawn**: it is the normal account sign-in of `15` page 2; it is not in the inventory | none |
| Today's admin adds a person with a temporary password | **Not carried over**: `32` has invitations and reset links only | as drawn |

Applied in this round to the earlier drawings: the strip's "Try again" is 48 px in all five files (the strip is 56 px tall, a little less than before), the Welcome TV frame shows a six-digit code, the YouTube Music data file is a grey "later" line, the Notifications page shows two categories, the Playback refusal comes from the owner's cap in the admin, and the three left-over wording fixes of rounds 2 and 3.

Still to do in the final consistency pass: the 48 px scrubber hit area and device button on the phone Now playing frame, and the profile avatar at the top left of the drawn Home (Spotify's place; the drawing still shows it at the top right). **Closed without being done (D-43, 2026-10-31): the drawings are history wherever the app has the screen, and the app has the avatar at the top left and no device button.**

---

<a id="design-04-review-2026-10-30"></a>
## design-04-review-2026-10-30 · design-04-review-2026-10-30.md

**Design 04: the review of every drawn screen against what is built (2026-10-30)**

### Design 04: the review of every drawn screen against what is built (2026-10-30)

The owner, 2026-10-30: check the design page screen by screen, say with the advisor what each one needs and which ones are missing, **criteria** included; draw what is missing (**phone and PC only**, D-18); then change the app to match. This file is the first step: **what exists, what differs, what is missing.** It builds on `00-screen-inventory.md` (what each screen must show) and does not repeat it. The drawn pages are in `directions/` (62 screens, 299 states; the page "Encore Design Choice" indexes them). Changing the app to match the frames is **RC2** and starts after the release-candidate rehearsal (`docs/tasks/RELEASE-CANDIDATE.md`, D-30); drawing the missing pages does not wait.

> **Status 2026-11-01.** This file is the snapshot of 2026-10-30 and its "Built" column has not been edited since. Three things changed what it means. **(1) D-43 (2026-10-31): the built screen is the reference wherever a screen exists**, so every "Proposed: redraw" and every "Frame is stale" below is void (the old frames are history, nothing is aligned to them) and "changing the app to match the frames" applies only to pages that do not exist yet. **(2) Built since:** a downloaded release as one entry (S-16, #63), the join page (W-05, #88), the three dots on every Library row that has a collection (S-14, D-26; artist rows have none, because the collection menu has nothing for an artist), the Home avatar's drawer (S-27, #60) and What's new (S-24, #35). **(3) D-48 a (2026-11-01): tablets are parked everywhere**, like TV and car. The "62 screens, 299 states" above count screens and states; the five drawing files hold 654 frames in all (120 + 172 + 130 + 164 + 68, counted 2026-11-01), and `directions/index.html` is the page that lists them.

#### The criteria every screen is judged against

1. **Every state the code can reach is drawn**: loading, empty, offline, error, permission, and the states of the decisions since (a refusal, a partial result).
2. **Familiar**: Spotify's arrangement and words where a person already knows them; one home for every action (no second copy of a control).
3. **Plain words**: what happened and what to do, no jargon, no red unless it is an error, one voice (`your`, not `my`).
4. **Honest**: no control that promises what the server cannot do (D-33, D-37), no placeholder or invented data; a new person sees something real or nothing.
5. **Works at 200% text and in both themes**, with a 48 dp target for every control, and reads aloud (labels).
6. **Phone (C) and PC (X) only** (D-18): TV, tablet and car frames are parked.
7. **A joining friend's path is judged on its own**: from the link in a message to the first song, on a phone that does not have the app yet.
8. **A screen shows only what this server can do, decided by a capability, never by guessing the mode** (D-33, D-37).

Legend for "built": **yes** (built, and matches in the states that matter) · **part** (built, some states or details differ) · **no** (drawn, not built) · **parked** (D-18). "Frame is stale" means a decision since 2026-10-25 contradicts the drawing: it must be redrawn before the app is aligned to it.

#### First run and connecting

| ID | Screen | Built | What differs, or is missing | Proposed |
|---|---|---|---|---|
| S-01 | Welcome: find my server | part | Only the typed-address form exists (`connect_screen.dart`); "found one / found two", the QR and the link are P2-19 slices B and C. The album wall (D-31, D-38) is not drawn on it | RC2: build with P2-19; redraw for D-38 |
| S-02 | Join an invitation | yes | States built and tested; never walked on the release-candidate pair (J13) | keep |
| S-03 | Sign in | part | The same screen as S-01. "Sign in with a code from another device" needs the unbuilt pairing and the TV (F46) | drop that state |
| S-04 | Sign in again | yes | | keep |
| S-05 | Who is listening | yes | Reached from Settings > Switch user and from the drawer's block (D-34) | keep |
| S-06 | Bring your music (first run) | no | The Import page exists in Settings (three screens, M1); the first-run step "choose where from" and its "skipped" card do not | RC2 |
| S-07 | Pick a server | no | A person on two servers | later |
| S-08 | Sign in on a TV with a code | parked | | parked |

#### Home, search, browsing

| ID | Screen | Built | What differs, or is missing | Proposed |
|---|---|---|---|---|
| S-10 | Home | part | Full is built; **offline and unreachable: the strip is built, the lasting look (grey tiles and shelves with "Not downloaded" in words, and the "Downloaded, Plays offline" shelf) was drawn and not built until P1-15 (5 Nov 2026, built not walked)**; the "Can't reach your server" frame's Try again button is NOT built (D-45: said once, no button). **"New person: Start with something" (popular songs, moods, "Bring your music") is drawn and not built**: an empty account sees "Search for a song to start" and a button. No skeleton. The Jam chip appears only where the server has Jam (D-33) and the frame no longer matches. **Checked: the empty Home shows only when the track count is 0; the sync's first pass writes every song the server keeps, so a friend joining a server that has music gets the full Home ("New on the server"); the empty Home appears on an empty server, the owner's own first run** | **RC2, first in line**; redraw for D-38. "Popular songs" needs one server endpoint (the chart, D-38) that also feeds S-13 and the wall (today the phone fetches genre charts itself: thin-client debt) |
| S-11 | Search start | yes | Recents and Browse all built; Browse tiles look as drawn | keep |
| S-12 | Search results | part | To verify (UI tester): the frame has no marker of what is on the server (design review 2026-10-24); the build may still head a section "In your library" | verify; if it does, **later**, not RC1 |
| S-13 | Genre or mood page | yes | | keep |
| S-14 | Your Library | part | Rows have no menu (D-26); the "Downloaded" chip starts off the right edge on a phone (F56); sort and filter | RC1 (menus), later (chip) |
| S-15 | Liked Songs | yes | | keep |
| S-16 | Downloaded | part | One entry per release is built in #63 (not merged yet); "storage full" to verify | RC1 (#63) |
| S-17 | Playlist | part | Mine, shared, editing built; row and ⋯ menus per D-26 | RC1 |
| S-18 | Album | part | **Not drawn: a catalogue release being saved, kept, failed ("Couldn't get 2 songs: …") and the per-song Download (D-21, D-32)**; the page needs the network and has no cache | **draw, then build** |
| S-19 | Artist | yes | Honest about what the server holds ("1 of 15 albums on your server") | keep |
| S-20 | Imported playlist | yes | | keep |
| S-21 | Discography, Show all | yes | | keep |
| S-22 | Create | yes | "Import from Spotify or YouTube Music" is a second door to Import (M1) | keep |

#### Player, together, more

| ID | Screen | Built | What differs, or is missing | Proposed |
|---|---|---|---|---|
| S-23 | Recently played | no | Only an Android Auto browse node exists (the drawer leaves it out, D-34) | RC2 |
| S-24 | What's new | yes | Built (#35), never walked with real items | keep |
| S-25 | Song credits | no | | later |
| S-26 | A person's profile | no | | RC2 with friends (P4) |
| S-27 | The profile menu | part | Built as the drawer (#60) from rows whose place exists; "View profile" and "Recently played" left out (D-34) | keep, redraw to match |
| S-28 | Your account, edit profile | no | Picture, name, password, devices (RC2, D-27) | RC2 |
| S-31 | Now playing | yes | **Frame is stale**: draws the device icon (D-28) and a share icon that was never built | redraw |
| S-32 | Lyrics | yes | Fetched by the phone from the web (thin-client debt) | keep |
| S-33 | Queue | part | A lone "Save" (F55); recommendations rows not built | later |
| S-34 | Song menu, Add to playlist | part | Per-song Download / Remove download (D-32) not drawn | draw, then build |
| S-35 | Sleep timer, Speed, Equalizer | part | **Frame is stale**: draws Playback speed, removed (D-23) | redraw |
| S-36 | Devices | no | Needs P4-07 | later |
| S-37 | Share | no | | later |
| S-50 | Jam | part | Built; the server has no Jam (not started), so the app now hides every way in (D-33); the frame has no "Jam is not on this server" state because there is no way in | keep, later |
| S-51 | People and Invite someone | part | Built for owners; one invitation flow on an Encore server (M2 reasoned) | keep |
| S-52 | Year in Music | yes | | keep |
| S-53, S-54 | Friend activity, Taste match | later | The share switch is hidden on an Encore server (D-37) | later |
| S-60 | Import | part | Three screens where one is drawn (M1) | **RC1** (M1 is in D-29's cut-line) |
| S-61 | Requests | part | The old request portal still exists in plain mode; hidden by D-29 (M3, M5) | keep the frames until the M3/M5 check (do these surfaces appear in Encore mode at all?) is done |

#### Settings and system

| ID | Screen | Built | What differs, or is missing | Proposed |
|---|---|---|---|---|
| S-70 | Settings (the list) | yes | Sign out and Switch user are drawn here as well as in the drawer (D-34) | keep |
| S-71 | Your server | part | **Frame is stale**: draws the "Testing…" button (F40); words for Tailscale and the address (F39) | redraw, then build |
| S-72 | The settings pages (9) | part | Privacy page lost its scope radios (F41); the "Devices" page needs P4-07 | keep |
| S-73 | People and household | part | | keep |
| S-74 | About and diagnostics | yes | Version line and session line added (F34, F53) | keep |
| S-75 | Language, Accessibility | later | | later |
| S-90 | Connection strip | yes | | keep |
| S-91 | Failed edits | yes | | keep |
| S-92 | A permission is needed | no | Camera and storage drawn; **the Android 13 notification permission is not drawn** | draw |
| S-93 | Update needed | part | Server-too-old state exists in code; app-too-old is not built | later |
| S-94 | Lock screen, notification | yes | The media notification is built; the car display is parked | keep |

#### The server's own pages (PC)

| ID | Screen | Built | What differs, or is missing | Proposed |
|---|---|---|---|---|
| W-01 | Installer wizard | no | The installer is terminal text (F14). **Frame is stale** against D-19 (Where songs come from), D-20 (no YouTube sign-in), F17 (Tailscale), F23, F28, F39 | redraw, then build (RC2, P3-06) |
| W-02 | Admin: health | no | | RC2 |
| W-03 | Admin: people and invitations | no | | RC2 |
| W-04 | Admin: library, away from home, backups, updates | no | | RC2 |
| W-05 | Join page (a person without the app) | **no** | **Checked 2026-10-30: the server has no handler for `GET /encore/join/<code>` (its router is mounted and everything else goes to Navidrome), so a friend who taps the link gets Navidrome's page or a 404. On Android 12 and later the browser always wins for such a link (an arbitrary self-hosted host cannot be App-Link verified; the manifest has host `*`, no `autoVerify`). A dead end on the friend milestone.** | **RC1 (D-39)**: two pages (a valid one with "Open in Encore", the two steps and the link to paste; one identical page for every dead code) |
| W-06 | The web player | parked | D-18 | parked |
| W-07 | Admin: settings | no | | RC2 |
| W-08 | Admin: logs and diagnostics | no | | RC2 |

#### Pages that were never drawn (missing)

These are real states or pages that the code or a decision now needs and no frame shows:

1. **A catalogue release being saved, kept, failed, and the per-song Download** (S-18 and S-34; D-21, D-32).
2. **Row menus on Library and playlists** (long-press and ⋯; D-26).
3. **The album wall on the join and welcome screens, with its empty case** (D-31, D-38).
4. **The server's front page and the pairing QR at its address** (F16, P2-19 slice B): what a person sees if they open the address in a browser.
5. **The installer wizard as the decisions now describe it** (W-01 redrawn).
6. **The Android 13 notification permission** (S-92) and the downloads "waiting for Wi-Fi" state (S-16).
7. ~~**Search and Search results offline** (S-11, S-12: no offline state is drawn).~~ **Drawn 5 Nov 2026 (P1-16)**: the start page, results, no results and the genre page, offline, C and X, with the two-way split of the strip (no internet found / internet found and the server silent); see `00-screen-inventory.md` S-11, S-12, S-13.
8. **Sign out and "Remove from this device"**: the question and its words, drawn once (they are one action reached from three places).
9. **The new person's Home, redrawn for D-38** (S-10: where the "popular songs" come from, per region, fetched by the server).
10. **The invitation dialog when the server has no away-from-home address** (F39's wording, on the friend journey's path; the next batch can build it without a frame, but it is drawn so RC2 does not undo it).
11. **W-05, the join page** (drawn, to be built now: D-39).

**Order to draw (advisor; superseded by D-43, below: only a page that is new and about to be built is drawn, right before it is built):** 1 the stale redraws (S-31, S-35, S-71: the F46 revision pass, D-30); 2 S-10's new person and the wall on S-01 and S-03 (D-38); 3 W-01, the wizard; 4 the server's front page and QR (F16); 5 the release states and the per-song menu (S-18, S-34) and the row menus (D-26; these are built from the existing menus in RC1 and drawn afterwards as the RC2 target); 6 S-92, S-16 "waiting for Wi-Fi", S-11 and S-12 offline; 7 the sign-out question, drawn once. They go in a **new file** next to the five (same tokens, same figure and meta structure, phone and PC), with a card on the "Encore Design Choice" page.

#### Rule added 2026-10-31 (advisor): who may see the album wall (a security rule, D-41)

The wall (D-31, D-38) shows **real covers only, and never covers the server hands to somebody who is not signed in**: the server's front page, the invitation page (W-05) and the "Servers on this Wi-Fi" tile on S-01 show no covers of the library (the tile shows the plain Encore mark). Library covers on the welcome screens can only come from **this phone's own cache** (a phone that still holds another person's profile, for example when a second person is added on a shared phone); a first-time phone, and a phone after its last profile was removed (the cache goes with the profile), gets the regional-chart wall fetched by the server, or **no wall**. Drawn in batch 1 (S-01 and S-03), which D-43 withdrew (below): the file is removed and git keeps it.

#### Batch 1 was tried and not taken, 2026-10-31 (D-43)

A drawing agent redrew S-31, S-35 and S-71 and drew S-10 and the album wall on S-01 and S-03. **The owner looked at it and did not take it**: "a bit childish and confusing"; he prefers the current version, the one similar to Spotify ("spotify spent millions making that design and it worked for a reason, let's learn from it"). **The rule that follows (D-43, advisor): the built screen is the reference wherever a screen already exists, and a page is drawn only when it is new and about to be built, right before it is built.** The file was removed from the repository (git keeps it); nothing in it is a target. What stays from the work: the **content** fixes already in code (the address checks itself, plain words about Tailscale, "in your library", the offline lines, no device or share icon) and the **wall rule** above: library covers are never sent to somebody who is not signed in. A Welcome screen with no covers is never blank: it shows the Encore logo on the app's own dark ground (RC2, with the wall). The new person's Home is built from the Home shelves and cards that exist, in Spotify's new-account pattern, with no new visual style.

#### Open questions for the advisor

For each screen row: **keep, redraw, build now, build in RC2, or drop?** And whether the nine missing pages are the right nine, in what order they should be drawn, and what has been left out.

#### Verdicts (advisor, 2026-10-30)

* **This review is the F46 revision pass** (D-30): S-31, S-35, S-71 and W-01 are redrawn first.
* **RC1 from this review:** W-05 (D-39), S-60 (M1), and the row menus, per-song Download and release behaviour (D-26, D-32, D-21) which use the existing menus and do not wait for drawings.
* **RC2, in this order:** S-10 new person, the wall (S-01/S-03), the redrawn Your server (S-71), the wizard (W-01), the front page, the admin pages (W-02 to W-08), profile and account (S-26, S-28), Recently played (S-23).
* **Agreed as written:** every other row; S-03 loses its "sign in with a code" state; S-08 and S-06's TV parts stay parked.
* **Open decision D-40:** where a friend gets the APK (see `docs/10`): there is no store, and "Get Encore" must not point at an invented place.
