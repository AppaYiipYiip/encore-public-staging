# 07 — Testing: how to test like people use phones

Owner (2026-10-21): *"the tests we currently have feel like they are written by someone who has never used a phone before … provide
guidance to do better testing, better examples."* This page is that guidance. It is binding for implementing, reviewing and QA agents.

## 1. What was wrong with testing (diagnosis)

| Problem | Example from this project | Consequence |
|---------|---------------------------|-------------|
| Tests checked that the code does what the author intended, against fakes of the author's making | Jam tests used a fake song player; the real two-phone run found a 500-times re-add loop (B48) | "1,430 green tests" while a person hit 20+ problems in ten minutes (`01` §E) |
| Only the happy path, only the developer's phone setup | All walks on one emulator, gesture navigation, font 1.0, fast LAN | 3-button navigation, big fonts, offline, hard kills were untested |
| Measured the best case and reported it as the case | "tap → sound 3.6 s" was measured with the album page open 10 s before the tap; a person searching and tapping waits 38 s | Wrong decisions (`01` B7) |
| Measurement tools that lie | The phone's media session said PLAYING 2.9 s after a tap while the server was still searching (seen 2026-10-21) | A "pass" with no audio |
| No long, odd or foreign content | No 2-hour recordings, no Arabic titles, no age-restricted or missing songs | The 45-minute limit refusing a Surah went unnoticed |
| No time, no concurrency | No test runs for an hour, after a reboot, with two people importing at once | Rules for shared work never designed (`04` §10) |
| No exploring | Every test was scripted from the spec | Nobody tried "what if I tap five songs fast" or "what if I'm on a train" |

## 2. Reference setups (every number names its setup)

| Name | Server | Line (server side) | Phone |
|------|--------|--------------------|-------|
| **SLOW** | 2 vCPU, 2 GB VM (stand-in for a Raspberry Pi 4) | 10 Mbit/s down, 1 Mbit/s up, 40 ms (shaped with `tc … netem` on the VM) | Emulator 2 CPU, 2 GB, 720×1600, `-netspeed lte -netdelay umts` |
| **TYPICAL** | 4 vCPU, 4 GB (measured on the former dev VM `encore-dev`, destroyed 2026-11-03; the test VM 108 has 3 GB, so its memory numbers run a little worse than TYPICAL) | the real home line (~18 Mbit/s down, ~7 up, shared with a family) | Emulator 4 CPU, 4 GB, 1080×2400 |
| **REAL** | the dev VM | real line | the owner's phone + one friend's phone over the public address |

A result reads: *"tap → audible, never-played songs, p50 2.4 s / p95 3.8 s / max 6.1 s, n=12 distinct songs, TYPICAL, build 0.2.0+47"*.

## 3. Measuring correctly

* **"Audible" means audio is coming out.** Use the app's own span `perf play.audible`, logged when the player's position first passes
  200 ms after a tap (built in the engine, P1-06). Cross-check with `adb shell dumpsys audio | grep "state:started"`. Never use media-session
  state alone.
* **Never-played songs mean never played *on that server*.** Keep a list of used songs per server and pick new ones each run
  (§8 has a pool). Popular songs can be faster (YouTube's CDN); include obscure ones.
* **Report p50, p95 and max over ≥ 10 runs**, and the songs used. One run is an anecdote.
* **Separate the stages** in server logs (`search`, `extract`, `first_byte`, `proxy_start`) so a regression points at its cause.
* **Measure the person's path**, not a shortcut: search → type → results → tap, from a cold app and from a warm app.

## 4. The device matrix

Every user-facing change is walked on **profile A and profile B**; the full matrix runs before every release.

| Profile | Navigation | Font scale | Display size | Screen | Android | Theme | Locale |
|---------|-----------|-----------:|--------------|--------|---------|-------|--------|
| **A (small, hard)** | **3-button** | **1.3** | Larger | 720×1280 (5") | 10 (API 29) | light | `fr-FR` |
| **B (big, modern)** | gesture | 1.0 | Default | 1080×2400 | 16 (API 36) | dark | `en-US` |
| C | 2-button | 2.0 (max) | Largest | 1080×2340 | 13 | dark | `ar-MA` (right-to-left) |
| D | gesture | 0.85 | Small | 1440×3200 | 15 | dark | `en-US`, battery saver on |
| E | 3-button | 1.0 | Default | foldable/tablet 1840×2208 | 14 | light | `es-ES` |
| Real | owner's phone, a friend's phone; ideally one Samsung (One UI) and one Xiaomi (HyperOS), whose battery savers kill background apps | | | | | | |

**How to set a profile on an emulator** (no rebuild needed):
```
adb shell cmd overlay enable-exclusive --category com.android.internal.systemui.navbar.threebutton   # or .gestural / .twobutton
adb shell settings put system font_scale 1.3
adb shell wm density 340            # "Larger" display size on a 280-dpi device; `adb shell wm density reset` to undo
adb shell wm size 720x1280          # small screen; `adb shell wm size reset`
adb shell cmd uimode night yes
adb shell settings put global development_settings_enabled 1 && adb shell settings put global always_finish_activities 1   # "don't keep activities"
adb shell cmd connectivity airplane-mode enable
adb emu network speed gsm ; adb emu network delay gprs                    # slow network
adb shell am set-standby-bucket app.encore.player restricted              # battery-saver-like restrictions
adb shell cmd locale set-app-locales app.encore.player --locales ar-MA    # per-app locale (RTL)
```
Always reset after a run (the owner may use the emulator too).

**Automated equivalent (widget/golden tests, P1-12):** a `deviceProfiles` test helper pumps every screen under each profile:
`MediaQuery(data: …copyWith(padding/viewPadding: EdgeInsets.only(bottom: 48) /* 3-button */ or 24 /* gesture */,
textScaler: TextScaler.linear(2.0), size: Size(360, 640)))`, plus `Directionality.rtl`. For each it asserts:
* no `RenderFlex overflowed` and no clipped `Text` (a test hook checks `TextPainter.didExceedMaxLines` where `maxLines` is set);
* **no tappable widget's rectangle intersects the bottom system inset** (the owner's "buttons under the 3 navigation buttons");
* Flutter's accessibility guidelines pass: `expect(tester, meetsGuideline(androidTapTargetGuideline))`,
  `labeledTapTargetGuideline`, `textContrastGuideline`.
Goldens are stored for profiles A and B only (to keep them reviewable).

## 5. Network and life-cycle conditions

What the player is **supposed to do** in each condition below (and what it does today) is the failure matrix in **`33`** §4; this section is how to **test** it. Conflicts between devices: `34`.

| Condition | How | What a person must see |
|-----------|-----|------------------------|
| Offline from the start | airplane mode, cold start | Home from the phone's database ≤ 0.7 s; downloaded music plays; other rows greyed; one calm strip, once (`31` CN-1, D-45) |
| Lose network mid-song | airplane on at 1:00 of a streamed song | the song plays what is buffered, then pauses with "Waiting for connection"; **no skipping**; resumes by itself ≤ 5 s after the network returns |
| Flaky network | toggle airplane every 20 s for 5 min while playing a playlist | never stuck; no duplicate plays; play/pause always present |
| Slow network | `adb emu network speed edge` | tap → audible ≤ 10 s; a spinner, then sound; nothing frozen |
| Server down | `docker stop encore-server` on the VM | library and downloads work; "Your server isn't answering" only on actions that need it; recovers by itself |
| **Radio on, no data** (the state most phones live in away from home; **airplane mode is not it**) | stop `encore-server` on the dev VM while the phone is on Wi-Fi, or block the server address with the emulator's network controls; a real phone with mobile data switched off but the radio on | one strip once; downloaded songs play; a list with songs that are not downloaded plays only the downloaded ones (Play, Shuffle, Next, the end of a song); the title and cover shown are always those of the song heard (Now playing, mini player, notification, lock screen); lyrics say "no lyrics" within ~12 s, never a spinner |
| A partly downloaded list | download a playlist, take one song in the middle off the phone, go to the state above | Play and Shuffle start at a downloaded song; rows show which songs are downloaded (arrow) and, offline, dim the rest |
| A list deleted while downloaded (also an imported one) | delete the playlist | Library > Downloaded and "N songs on this phone" fall within seconds; the files are gone from Settings > Downloads & storage |
| A long outage | server stopped for 10 minutes | the strip appears once and goes by itself; not again until everything has worked for 10 s; the person is never asked for a password |
| A Wi-Fi sign-in page (captive portal) | a public Wi-Fi before its page is accepted (a real network; not simulated) | the app opens on Home with the saved server, never on the page that asks for a server; the page's answer is never read as the server's (a 200 page is no answer, a bare 401/403 is not "sign in again") |
| YouTube refusing | server fault flag `ENCORE_FAULT=youtube_refuse` (built: `sources/youtube/stream.py`) | taps fail in ≤ 10 s with one plain sentence; imports pause; admin Health explains |
| Hard kill while playing | `adb shell am force-stop app.encore.player` | reopen: same song, paused at the same second (± 2 s) |
| System kill in background | HOME, then `adb shell am kill app.encore.player` | same as above |
| Reboot | `adb reboot` | same as above; downloads intact |
| Another device takes over | play on emulator B with the same account | A pauses ≤ 2 s and says where it is playing |

## 6. Test levels and what each must prove

| Level | Proves | Example that is **good** | Example that is **bad** (do not write) |
|-------|--------|--------------------------|----------------------------------------|
| Unit | One rule in isolation | Scheduler: with 2 people, one with 2,000 `keep` items and one with 20, the 20 finish before item 100 of the 2,000 (fair share, `04` §10 rule 4) | "`resolve()` calls `searcher.search()` once" (tests the implementation, not the rule) |
| Property | A rule holds for all inputs | Matching: normalised(title, artist) is equal for `"Kifak Inta"`/`"كيفك إنت"`? → no; for `"Beyoncé"`/`"Beyonce"` → yes; never matches `"Animals"` to `"Animals as Leaders"` | — |
| Contract | App and server agree on the API | The app's parser accepts the server's recorded responses for every endpoint; the server's OpenAPI schema is checked in CI | A hand-written JSON the server never produces |
| Server integration | Real parts together | Real Navidrome in Docker + the server: like a catalogue song → keep job → file appears → ref gets a file id → like still there; YouTube answered from recorded fixtures | Navidrome mocked |
| Live canary | YouTube still works | 1–3 real look-ups per night (a fixed obscure song), alert if the stage times move by >2× | 200 look-ups "to be sure" (`06` §8) |
| Widget/golden | A screen is right on every profile | Search results screen at profile A: Top result first, nothing under the nav bar, all rows labelled | A golden at one size only |
| On-device journey | A person's task works end to end | §7 journeys on emulators against the dev VM, measured | A journey against `FAKE_MODE` |
| Exploratory | What nobody thought of | §9 charters | — |
| Field | Real phones, real lives | Owner + a friend use a beta for 5 days; issues filed with the template | — |

## 7. Journeys (examples written the right way)

Each journey: setup, steps a person does, what they must see, numbers, evidence. QA agents run them on profiles A and B.

**J-01 A friend joins from an invitation (wiped phone).** Setup: profile A, app installed fresh (`pm clear`), Host made an invite.
Steps: open the invite link from a message → the app opens → enter a name and password → Join. Expect: no server address asked;
signed in ≤ 10 s after Join; the "Bring your music" screen (US-05); Skip → Home is not empty. Evidence: screenshots of each screen
(never with the password visible), time from Join to Home.

**J-02 Search and play a never-played song.** Setup: profile B, TYPICAL, a song from the pool never used on this server.
Steps: Search → type the artist and title → tap the Top result. Expect: the typed song is the Top result; audible ≤ 2 s p50 / ≤ 4 s
p95 / ≤ 10 s max over 12 different songs; the previous song stops at the tap. Evidence: `perf play.audible` lines, server stage
times, the 12 songs.

**J-03 Play a partly owned album to the end.** Lateralus (2 of 13 on the server). Play → Next ×12. Expect: all 13 play in order,
Next never disabled, each change ≤ 1 s (prepared), the album is not added to the library.

**J-04 Import a real playlist.** YouTube Music "'00s Hip Hop" (189 songs, `RDCLAK5uy_n4g8XbXdlPTtik7Fwl4RU3Gij-63HBsmo`).
Steps: share the link to Encore (or paste) → Import. Expect: the playlist with its cover and **189** songs in Your Library ≤ 5 s;
tap song 57 → audible ≤ 3 s; Stop → no new server work starts (server log); counts agree on Home, the playlist and the import card.

**J-05 Two people, overlapping imports, same time.** Two emulators (two accounts). A imports playlist X; 30 s later B imports Y,
which shares 20 songs with X. Expect: B's shared songs need no new look-ups (server log: joined/reused); neither import's first
screenful waits for the other; both can play any song at once.

**J-06 Plane mode.** Download album Animals; airplane on; cold start. Expect: Animals plays with covers in the row, mini-player,
full player and notification; a non-downloaded playlist's rows are greyed; tapping one says "Not downloaded" once; no skipping.

**J-07 Lose and regain the network mid-song.** Stream a catalogue song; airplane on at 0:40, off at 1:20. Expect: audio until the
buffer ends, then paused with a waiting state; resumes ≤ 5 s after the network returns; play/pause button always present.

**J-08 Hard kill while playing.** Play at 2:31; force-stop; reopen. Expect: mini-player shows the song paused at 2:31 ± 2 s.

**J-09 Continue on another device.** Emulator A plays song S at 1:10; pause. Emulator B (same account) opens. Expect: B shows S
paused at 1:10; Play on B → audible at 1:10 ± 1 s; then Play on A → B pauses ≤ 2 s and shows "Playing on <A>".

**J-10 A 2-hour recording.** Search "Surah Al-Baqarah Mishary". Expect: audible ≤ 4 s; drag the seek bar to 2:00:00 → audible ≤ 2 s;
lock screen seek bar shows the right position; background-keeping it does not fail for length (only disk space can stop it).

**J-11 Big text and 3-button navigation, every screen.** Profile C. Walk Home, Search, Library, album, playlist, player, queue,
lyrics, every sheet (song menu, add to playlist, sleep timer), Settings and each sub-page, Import, sign-in. Expect: no clipped word,
nothing under the navigation buttons, every button reachable and labelled (TalkBack reads it).

**J-12 Server restart during an import.** Restart the server container at 30 % of an import. Expect: the import continues by itself
within 1 minute; no song twice in the playlist.

**J-13 YouTube refuses.** Fault flag on. Expect: taps on catalogue songs fail in ≤ 10 s with one sentence; owned songs fine;
imports show "Paused, YouTube is busy, will continue later"; admin Health explains.

**J-14 New Host, clean machine.** A fresh Ubuntu 26.04 VM. Run the install command from the website; complete the wizard; invite a
phone; play a song. Expect: ≤ 15 minutes; no Docker word on any screen; the guide's steps match what happened.

**More journeys** (devices, offline playlist edits, cross-server Jam, battery saver, calls): J-15 … J-20 in `14` section 3.

## 8. Test data: real, varied, never placeholders

| Kind | Real example | Why it is in the pool |
|------|--------------|-----------------------|
| Everyday popular | Daft Punk – Instant Crush; Nas – N.Y. State of Mind | CDN-warm baseline |
| Obscure | Oum – Taragalte; Mehdi Nassouli – Mimouna | cold CDN, weak matches |
| Very long | Surah Al-Baqarah (Mishary Alafasy) 2:21:21, 163 MB | length limits, seeking |
| Long prog | Opeth – Windowpane 7:45; Pink Floyd – Dogs 17:04 | keeper limits, gapless |
| Non-Latin titles | Fairuz – Kifak Inta (Arabic), BABYMETAL (Japanese), Alcest – Améthyste (accents) | normalisation, RTL, fonts |
| Covers vs original | "Weird Fishes" (Radiohead vs covers) | ranking, matching |
| Same title, different artists | "Animals" (Pink Floyd) vs Animals as Leaders | matcher strictness |
| Age-restricted | Overnight Celebrity (Remix) – Twista ft. … (`4uEUiodPr7E`) | honest failure |
| Real playlists | YTM "'00s Hip Hop" (189); Spotify `3dEfExamplePlaylistC03` (100+ cap), `3dEfExamplePlaylistA01` (69) | import paths, 100 cap |
| Accounts | new test accounts on the test VM, made through invitations (CT 104 and its accounts `tester`, `nina`, `mia`, `friend` were destroyed on 2026-11-03; the login files for them in `..\local\logins\` no longer work) | real multi-user |

Fakes are fine inside unit tests for one rule; a journey passes only with real data made through the app (owner's rule).

## 9. Exploratory charters (30–60 minutes each, write findings as issues)

1. **"Break the player":** tap five different songs within 3 s; seek while loading; next/previous spam; play/pause spam during a
   network drop. Goal: the player is never stuck and always shows a working play/pause.
2. **"On a train":** flaky network profile for 30 minutes of real listening with a mixed playlist.
3. **"Grandmother":** profile C + TalkBack on; join from an invite; play a song; make a playlist.
4. **"The switcher":** a real Spotify user's data export file; import everything; compare counts with Spotify.
5. **"Weird links":** shortened links, links with tracking parameters, album links, artist links, a private playlist, a deleted
   playlist, a YouTube video link, a podcast link. Every case gets a plain answer.
6. **"Host's bad day":** disk almost full, YouTube refusing, Funnel key expired, server rebooted mid-import.

## 10. The screen checklist (read every screenshot with it)

* **Understand:** would a non-technical person know what this screen is for and what to tap? Any jargon?
* **Complete:** does every row have a cover (or a deliberate one), a title, a subtitle? Are counts right and consistent with other screens?
* **Honest:** does the screen claim something that is not true (PLAYING without sound, "ready" when stopped, a playable look on a
  song that cannot play)?
* **States:** loading, empty, error, offline: is each one designed or accidental?
* **Layout:** nothing clipped, nothing under the status bar or navigation buttons, works in RTL.
* **Access:** every control labelled, targets ≥ 48 dp, contrast ok.
* **Feel:** does it respond within 100 ms of a tap (even if only with a spinner)?

## 11. Pass, fail, evidence

* A journey **passes** only with its evidence attached (screenshots per step, numbers with setup, server log excerpts).
* Any **S1** or **S2** found blocks the release; S3s are filed and scheduled.
* A test that cannot run (tool broken, permission) is **"not run"**, never "pass".
* The QA agent writes a short report per run: what was run, on which profiles/setup, results, new issues, what was not run.

## 12. The walk record: expected, got, verdict (owner, 2026-10-24: "we don't have a *this is what is expected and this is what I got* document")

Every walk (a journey, a charter, a device check, a fault test) is written in one shape, so anybody can see what was supposed to happen, what did, and whether the two agree. The **expected** column is filled in **before** the walk, and it is not invented while testing: it is copied from a row of the state tables (`31` connecting, `32` accounts and joining, `33` playback, `34` conflicts), from a story (`03a`) or from a journey step (§7). **If no row says what should happen, that is the first finding:** write the row (in the right table), then walk.

| Column | What goes in it |
|--------|-----------------|
| **Row** | The id it is checked against: `CN-11`, `IV-8`, `J4 step 3`, a story number. Several walks may check one row; one walk usually checks several |
| **Setup** | The state it starts in, in plain words: build and phone, server up or down, which addresses are saved, signed in or not, what is playing, which network. Enough for somebody else to arrive at the same state |
| **Steps** | What the person does, in order, as taps and typing. No shortcut a person could not take |
| **Expected** | Copied from the row. What the person sees or hears, a number with its limit where there is one. **What must not happen counts too** ("no request carries a login") and is checked the same way |
| **Got** | What really happened: the text on the screen as shown, a number and how it was measured, a log line. Never "worked" or "fine" |
| **Verdict** | **Pass**: got matches expected. **Fail**: it does not (a *better* result than expected is still Fail until the row is changed, on purpose, with the reason). **Not run**: it could not be run (say why). **Blocked**: something else has to be fixed first (say what) |
| **Evidence** | The file in `docs/evidence/`: screenshot, log, timing output. A Pass without one is a "Not run" |
| **If Fail** | Severity (S1 to S3, §11), the issue number, the row or task that will fix it |

Rules that go with it:

1. **One table per walk, at the top of its evidence document**, then the setup details, the findings that are not rows, **Not covered** (rows nobody walked: they are listed, never silently skipped) and the YouTube look-ups spent.
2. **Walk a state, not a screen.** The unit is a row of `31` to `34`. A screen with no row behind it is a gap in the paper, and the gap list is simply the screens whose states nobody wrote: add a row first.
3. **Negative and fault rows are first-class.** For every "happy" row there is a row for *the server does not answer*, *another server answers*, *the line drops mid-song*, *the answer is slow*, *the answer is garbage*; each has an expected line like any other.
4. **A fix needs its walk repeated.** A Fail closed by a code change is re-walked on the same setup and the second record sits beside the first (same table, a new Got/Verdict pair), so "fixed" is an observation.
5. **Before / after for any change that touches speed or security** (the first example is `evidence/README.md#b03`): the same setup on the old and the new build, in the same session, and both numbers in the pull request.

Template (copy it):

```
# <id> — <what was walked> (<date>, build <n>)

| Row | Setup | Steps | Expected | Got | Verdict | Evidence | If Fail |
|-----|-------|-------|----------|-----|---------|----------|---------|

## Setup in detail
## Findings that are not rows
## Not covered
## YouTube look-ups spent
```
