# P5 — Public release

## P5-01 — Release signing and the release pipeline — Size S
* **Read first:** `../12-app-signing-key.md` (the agreed plan, in plain words, and the rules).
* **Why.** D6: "release" APKs are signed with the PC's debug key; changing keys later forces every user to reinstall.
* **Do.** Generate the release keystore with the owner (D-10: he keeps it + a backup); CI secret; `release.yml` signs the APK on tags
  `v*`, attaches it with SHA-256 checksums to the GitHub Release, pushes server images. Existing testers (owner, friend) do one
  uninstall/reinstall, announced in the release notes (their library is on the server; downloads re-download).
* **Acceptance.** `apksigner verify --print-certs` shows the release certificate; a tag produces a Release with APK + notes + images.

## P5-02 — In-app update check — Size S
* **Why.** A website-distributed APK has no store updates; YouTube changes make updates urgent sometimes. ADR-018 removed the inherited
  updater (it pointed at the upstream project's releases); this one points at Encore's.
* **Do.** Once a day (and on Settings → About) read the latest Release; if newer, a quiet card "Update available" → download the APK →
  Android's installer (`REQUEST_INSTALL_PACKAGES`); never nag more than once a week; a "beta" channel switch for testers.
* **Acceptance.** From build N, the app finds N+1, installs it in two taps, keeps all data.

## P5-03 — Full device matrix and the field test — Size M + 5 days
* **Do.** All journeys of `../07` §7 on profiles A–E and two real phones (ideally one Samsung and one Xiaomi); fix S1/S2; then the
  owner and one friend daily-drive the beta for 5 days, filing issues with the template.
* **Acceptance.** No open S1/S2; the owner does not open Spotify for 5 days.

## P5-04 — Cold start ≤ 0.7 s on a mid-range phone — Size M
* **Why.** E19: 1.2–1.5 s on the reference emulator, 3.7 s first start after install.
* **Do.** Profile start-up (`flutter run --profile --trace-startup`); defer non-visible work (sync, websocket, image cache warm-up)
  until after the first frame; check the database open and the first query; consider a baseline profile for ART.
* **Acceptance.** `adb shell am start -W` TotalTime ≤ 700 ms p50 over 10 runs on a mid-range phone; ≤ 1.5 s on profile A's emulator.

## P5-05 — The website — Size M
* **Not now (owner, 2026-10-21: "let's not worry about website, name and things like that").** Start only when the owner asks.
* **Do.** Static site in `website/` (built from `docs/guides/`), hosted on GitHub Pages with the owner's domain (D-9): landing (what
  Encore is, screenshots, "free, no subscription"), Install in 3 steps (Linux install video link, the command, the wizard), Download
  (APK + checksum + "how to install an APK"), FAQ (Docker never needed; what hardware; away from home; privacy), **Where songs come
  from** (plain: your files, and YouTube for the rest; switch it off; your responsibility where you live), Privacy, Terms, Source code.
  Final product name decided first (D-5).
* **Acceptance.** A person who never used Encore follows only the website and gets a friend listening (P3-07 + one real outsider).

## P5-06 — Go public — Size S
* **Do.** Repo public (GPL-3.0), images public, first release `v0.9.0` (beta) then `v1.0.0` after P5-03; announce where the owner wants.
* **Reports from people the owner does not know (ADR-R36).** Issues switched on; the owner's GitHub notification e-mail for new issues checked (it
  is on by default for the owner of a repository); "private vulnerability reporting" switched on (`SECURITY.md` already asks for it); the issue form
  asks for the app's technical details; the in-app report screen gets one more line for people whose server's owner is not somebody they can
  message ("A bug in Encore itself: open an issue at github.com/<owner>/encore/issues", with the message already copied).
* **Acceptance.** `gitleaks` clean on the full history; no homelab or personal data anywhere (`git grep -iE "192\.168\.|tail[0-9a-f]{6}|appayiip"` reviewed).

## P5-07 — Android developer verification and how people install the APK — Size M
* **Parked (owner, 2026-10-21): GitHub only, nothing paid, not now.** Keep only the install guide part when P5 starts.
* **Why.** `../26` H43, H44: from 2027 worldwide (since 30 Sep 2026 in some countries) apps on certified phones must come from a verified
  developer even when installed from a website; installing APKs is hard for ordinary people.
* **Do.** With the owner (D-17): a **limited distribution** account (free, 20 devices) for the beta now; a **full** account ($25, ID)
  before the public release; register `app.encore.player` with the release key (`../12`). Evaluate Obtainium (installs and updates
  from GitHub Releases) and F-Droid as channels. Write the install guide with screenshots for Samsung, Xiaomi and Pixel ("Install unknown
  apps", Play Protect), linked from the invite page.
* **Acceptance.** A non-technical person installs the APK from the guide on a Samsung and a Xiaomi without help; the registration is
  done before the first public release.

## P5-08 — What's new and in-app help — Size S
* **Why.** `../27` §1.
* **Do.** After an update, one card "What's new" with 3 lines from the release notes; Settings → Help: short answers (how songs reach
  you, away from home, downloads, Jams, privacy) linking to the guides; "Report a problem" (P4-13) from the same place.
* **Acceptance.** The help answers are written in the screen checklist's plain words (`../07` §10) and reviewed by the owner.
