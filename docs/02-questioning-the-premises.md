# 02 — Questioning the premises

The owner asked (2026-10-21): *"how come you didn't question the usage of YouTube here and things like that. Be curious, try to
understand why we are doing things."* This page does that for every big assumption the project rests on. For each: what was
assumed, why it was chosen at the time, whether it still holds (with evidence), the verdict, and why the verdict beats the
alternatives.

Verdicts: **Keep**, **Change**, **Drop**, **Later** (park, do not build now), **Owner** (needs the owner's decision, see `10`).

---

## Q1. "Songs you don't own come from YouTube."

* **Why it was chosen.** The owner wants to play anything, for free. The only sources of nearly every song, full length, at no
  cost and with no account are YouTube/YouTube Music (official "Topic" uploads by labels), peer-to-peer networks (Soulseek,
  torrents) and ripping paid services (Deezer/Qobuz/Tidal with a paid account). The library already came mostly from YouTube.
* **Does it hold?** Partly.
  * *Catalogue:* yes. YouTube Music has almost everything. In today's tests 5 of 5 everyday songs (Khruangbin, Daft Punk, Opeth,
    Nas, Fairuz) were found and correctly picked by YouTube Music's own top "song" result.
  * *Cost to the user:* free. That meets the owner's "free for the user" rule. Tidal, Qobuz and Deezer ripping all require a
    paid account, so they fail it. Spotify itself now includes lossless at $12.99/month (US, Feb 2026), so "better quality than
    Spotify" is not a selling point any more. Free, plays anything, and your own server are.
  * *Quality:* YouTube's best audio is Opus ~130–160 kbps (itag 251). That is about Spotify "High" (160 kbps). It's good enough
    for nearly everyone; it's not lossless.
  * *Fragility:* YouTube changes things monthly (PO tokens, JavaScript challenges, SABR). Today only the `visionos` player client
    returned audio without a PO token (`web`, `web_music`, `android_vr`, `web_safari`, `tv` all failed). yt-dlp keeps up, but
    only if it is updated often.
  * *Allowance per address:* YouTube limits how much one internet address may fetch (yt-dlp's guidance: ~300 videos/hour for a
    visitor). A home server shares one address with the whole family; a VPS address is often refused outright; some CGNAT
    addresses are already flagged; in some countries YouTube is blocked or throttled.
  * *Legal and terms:* downloading from YouTube breaks YouTube's terms in every country; whether it is also illegal depends on
    the country. A public website that ships it must say so plainly.
* **Verdict: Keep, but contain it.** YouTube is the only source that meets "free + plays anything". It becomes one **source
  module** behind an interface (`04` §4) with: no bulk "download everything" requirement for the user experience (P2-04),
  conservative paced background work with automatic back-off, no Google account anywhere on the server, an honest first-run
  notice in the app ("Songs that aren't on your server come from YouTube"), and a switch to turn it off. The product must still
  be a complete player without it (a pure library player), because in some places it will not work.
* **Why this beats the alternatives.** Soulseek and torrents: free but slow (minutes to days), unreliable for obscure music (the
  earlier test found zero peers for four albums), and legally worse (you also share). Paid-service ripping: fails "free". No
  catalogue at all: then Encore is a Plexamp clone, and "make Spotify look stupid" fails. A licensed catalogue: none is free.

## Q2. "The home server fetches the song before the phone can play it."

* **Why.** ADR-040 decided the phone should not run YouTube extraction (it breaks often, and needs a JavaScript engine in the
  app). So the server became the fetcher: download, tag, add to the library, scan, and only then (or from the growing file) play.
* **Does it hold?** The *place* is right; the *method* is wrong.
  * The method made playing wait for the server's whole pipeline: 38 s measured.
  * The server can resolve a stream in **3.0–4.0 s** with one YouTube Music search and one extraction in a warm process, even
    under the 3 Mbit/s cap (measured, `09` §2). From a home PC directly it was 2.0–4.3 s, which is no big win, because YouTube's
    own response time dominates, not the line.
  * Server-side resolution means one place to update when YouTube changes (the container updates yt-dlp), a cache shared by
    everyone on the server, and no YouTube code in the APK.
* **Verdict: Change the method, keep the place.** The server *resolves and streams* (proxy with Range support, keeping a copy
  as it streams); it does not make the person wait for a download, tagging or a scan. Look-ups for what a person is likely to
  tap next happen ahead of time (P1-04), which brings the common case under 1 s. On-device extraction stays a researched
  fallback (X-3 in `10`), not v1.
* **Why it beats on-device extraction now.** Measured gain is ~1 s at most at home. It costs an extractor in the APK that
  breaks when YouTube changes, with no Play Store auto-update to fix it fast, and a second code path to test.

## Q3. "Every song you play becomes a file in your library."

* **Why.** Before audio could only come from a library file (see Q2).
* **Does it hold?** No. Spotify separates *play*, *save* (like / add to playlist / save album) and *download*. Saving on play
  fills the disk and the library with every song someone tried.
* **Verdict: Change.** Play streams. **Save** (like, add to a playlist, save an album, import) makes the server **keep** the
  audio in the background. **Download** puts it on the phone. (P2-03.)

## Q4. "Import means bringing the audio over."

* **Why.** Same root as Q2: a song only existed once its file existed.
* **Does it hold?** No. Measured today, the *list* of a real 189-song YouTube Music playlist reads in **2.4–3.2 s** with every
  song's video id. Spotify playlists read in 2.2–3.5 s (100-song cap via the public page). That is Spotify-speed.
* **Verdict: Change.** Import = read the list → create the playlist (seconds) → every song plays on tap → the server keeps the
  audio in the background, paced safely. A person never waits for the background. (P2-04.)
* **About "2 hours is still a lot" (owner).** The background part is bounded by YouTube's allowance per address, which no
  number of threads beats (one burst test today did 188 look-ups in 53 s without a refusal, but YouTube's limits are not
  published, differ by address and change; a product for strangers cannot depend on bursts). So the design makes the background
  *not matter*: everything is playable at once, downloads to the phone are taken from the server's copy when it exists, and
  what you actually play goes first in the queue.

## Q5. "Signing a Google account into the server raises the limit, so we build a browser-in-a-page for it."

* **Why.** To get ~2,000 videos/hour instead of ~300 (yt-dlp guidance) for imports.
* **Does it hold?** No. yt-dlp's documentation warns accounts can be banned for this; for most people their Google account is
  their Gmail, photos and phone. It also needed Docker's socket in a web service (root-equivalent) and a 1.2 GB Firefox image.
* **Verdict: Drop.** Imports no longer need bulk speed (Q4). A cookies file stays possible only as an *Advanced, at your own risk*
  setting with a throwaway account, documented, not built into the UI.

## Q6. "The quality tier: Lidarr + slskd + Soularr fetch lossless copies over Soulseek."

* **Why.** The owner's homelab did it; "better than Spotify" quality.
* **Does it hold?** Not for v1. Three heavy containers (1.6 GB Soularr image), Lidarr's metadata server is a single point of
  failure (2025 outage), the real Soulseek network found nothing for the test albums, peer-to-peer sharing is the riskiest legal
  exposure, and Spotify now ships lossless anyway.
* **Verdict (owner, 2026-10-21): in the first version** (phase P4), rebuilt on song refs (a better file is just a new `file_id`, no
  upgrade map), switched on by the Host in the admin (off until then, because of the legal exposure and the three extra containers).

## Q7. "One music folder per person."

* **Why.** Privacy: friends should not see each other's music (ADR-075, agreed at the time).
* **Does it hold?** It solves privacy at the wrong layer. Two people playing the same song store it twice; folder naming rules
  and a provisioner exist only for this. In Spotify everyone shares one catalogue and *your* library is what you saved.
* **Verdict: Change, owner decision D-2.** One shared pool of kept audio; each person's library is the set of their saves
  (likes, playlists, saved albums), private by default. What someone listens to is never shown to others unless they turn
  friend activity on. The owner's existing collection can still be a separate library visible only to him (Navidrome
  multi-library), as an option.

## Q8. "Navidrome is the music server."

* **Why.** Mature, light (17 MB RAM measured), multi-user, speaks the Subsonic API that many apps use, transcodes, smart playlists.
* **Does it hold?** Yes for files, scanning, streaming, transcoding, users. No as the store of a person's library (see C3: it
  cannot hold songs without files, and file swaps change ids).
* **Verdict: Keep Navidrome for files, users and streaming. Encore's server owns each person's library** (songs as references
  that may or may not have a file yet), playback state, imports and invitations. (`04` §3.)
* **Why not replace Navidrome?** Rebuilding scanning, tag reading, transcoding and the Subsonic API is months of work for no user
  benefit, and power users keep their favourite Subsonic apps.

## Q9. "Each feature is its own service."

* **Verdict: Change.** One Encore server program (modules inside), one port, one login, one database (`04` §2). Six services
  bought nothing here (no separate teams, no separate scaling) and cost six ports, six auth checks, copies of the same client
  code, a capability-discovery layer, and a fragile install.

## Q10. "Tailscale Funnel for away-from-home."

* **Why.** Works behind CGNAT with no router change, no domain, TLS on the owner's machine, free (ADR-083).
* **Does it hold?** Yes, measured working (friend journey over the public address). Caveats: a Tailscale account is needed, two
  admin-console clicks, a 180-day key expiry, an unpublished bandwidth ceiling. The *owner's upload* (measured ~7 Mbit/s) is the
  real ceiling for listeners away from home, and many people have far less (ADSL uploads of 0.5–1 Mbit/s).
* **Verdict: Keep**, but (a) move the steps into the setup wizard with screenshots, (b) only Encore's single front door is
  published, (c) away-from-home streams default to Opus 96–128 kbps so a slow upload serves several listeners, and (d) songs
  you don't own are streamed by the server from YouTube for away-from-home listeners too (small: ~17 KB/s per listener).

## Q11. "An admin website that controls Docker."

* **Verdict: Change.** Keep a small admin site inside the Encore server (setup wizard, people, storage, remote access, health,
  updates). Drop Docker control: updates are one command (`encore update`) shown on the page.

## Q12. "Flutter for the app."

* **Why.** Inherited; mature audio stack (`just_audio`, `audio_service`); Android now, iOS/web/desktop later.
* **Does it hold?** Yes. The owner wants a future web/PC client; Flutter can target web and desktop with the same data layer, and
  the server's API is client-agnostic anyway.
* **Verdict: Keep.**

## Q13. "A fork of an existing player."

* **Verdict: Drop** (owner, 2026-10-21: "drop anything related to [the old project], name, reference or anything"). A fresh repository with
  only Encore's own files, after checking nothing copied remains (P0-04). Only 1 of 197 `lib/` paths even exists upstream.

## Q14. "Spotify import through a Spotify developer app (OAuth)."

* **Why.** To read private playlists and Liked Songs, and lists over 100 songs.
* **Does it hold?** No. Since February 2026 Spotify's development mode requires the app owner to have **Premium**, allows 5 users,
  and is "moving away from client credentials" (`09` §4). Asking people to pay Spotify in order to leave Spotify is absurd.
* **Verdict: Change.** (1) Public link → first 100 songs (works today). (2) Spotify's "Download your data" file → everything
  including Liked Songs (works today, but takes Spotify days to send). (3) Researched: the person signs in to Spotify's own web
  page inside the app on their phone, and the app reads their playlists and Liked Songs the way Spotify's web player does
  (experiment X-4). No developer app, no server-side Spotify login.

## Q15. "Jam, Year in Music, friend activity, recommendations now."

* **Verdict (owner, 2026-10-21): everything is in the first version**, even if the release waits months: Jam and friend activity on
  the new live channel, recommendations with a profile per person, the quality tier, Year in Music. They are built in phase P4,
  after the core (P1–P3) works, so they stand on the new design instead of wrapping the old one.

## Q16. "Python standard library only, one thread per request."

* **Verdict: Change.** An async web framework (Starlette/FastAPI on uvicorn) for streaming audio through, websockets for the live
  channel, and SQLite for state. `yt-dlp` is Python, so Python stays the server language: it can run yt-dlp in the same process
  (the main speed win, P1-01).

## Q17. "Builds are tested by the agent that wrote them; ~1,400 tests prove quality."

* **Verdict: Change.** Tests by people-like walks on several devices and nav modes (`07`), an independent reviewing agent per PR
  (`06` §4), acceptance criteria written as what a person sees with numbers, and real-network measurements labelled with the
  line and machine they ran on.

## Q18. "minSdk 24 (Android 7)."

* **Verdict: Change to 26 (Android 8.0).** Android 7 is a negligible share in 2026, and each old version widens the test matrix.
  Revisit if the website's download statistics show demand.

## Q19. "The owner's homelab is the reference server."

* **Verdict: Drop** (owner: separate projects). Encore is proven on a clean Linux VM and on the owner's machine as just another
  user, never by editing his homelab. His 3 Mbit/s cap showed why: a product must not assume one particular machine or line.
