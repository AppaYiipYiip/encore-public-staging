# P5 — Public release

## P5-01 — Release signing and the release pipeline — Size S
* **Order.** Needs: none.
* **Moved up (2026-11-03).** It comes before the *final* release-candidate build, not after the first outside user: the walk record `b11` must be of the binary a friend will actually install, and this task's own text says that changing the key later forces every user to uninstall and lose their downloads. The keystore is made with the owner (D-10).
* **Read first:** `../12-app-signing-key.md` (the agreed plan, in plain words, and the rules).
* **Why.** D6: "release" APKs are signed with the PC's debug key; changing keys later forces every user to reinstall.
* **Do.** Generate the release keystore with the owner (D-10: he keeps it + a backup); CI secret; `release.yml` signs the APK on tags
  `v*`, attaches it with SHA-256 checksums to the GitHub Release, pushes server images. Existing testers (owner, friend) do one
  uninstall/reinstall, announced in the release notes (their library is on the server; downloads re-download).
* **Acceptance.** `apksigner verify --print-certs` shows the release certificate; a tag produces a Release with APK + notes + images.

## P5-02 — In-app update check — Size S
* **Order.** Needs: P5-01 [i]. Why: the update check reads Encore's own signed Releases, which P5-01's pipeline produces..
* **Why.** A website-distributed APK has no store updates; YouTube changes make updates urgent sometimes. ADR-018 removed the inherited
  updater (it pointed at the upstream project's releases); this one points at Encore's.
* **Do.** Once a day (and on Settings → About) read the latest Release; if newer, a quiet card "Update available" → download the APK →
  Android's installer (`REQUEST_INSTALL_PACKAGES`); never nag more than once a week; a "beta" channel switch for testers.
* **Acceptance.** From build N, the app finds N+1, installs it in two taps, keeps all data.

## P5-03 — Full device matrix and the field test — Size M + 5 days
* **Order.** Needs: P4-06 [p]. Why: the device matrix and the field test run on the finished feature set, after the whole-app walk..
* **Do.** All journeys of `../07` §7 on profiles A–E and two real phones (ideally one Samsung and one Xiaomi); fix S1/S2; then the
  owner and one friend daily-drive the beta for 5 days, filing issues with the template.
* **Acceptance.** No open S1/S2; every promise N1 to N11 (`../03` §4) is measured on the reference setups SLOW and TYPICAL (`../07` §2) and on two real phones, with the numbers in the report; the owner does not open Spotify for 5 days.

## P5-04 — Cold start ≤ 0.7 s on a mid-range phone — Size M
* **Order.** Needs: none.
* **Why.** E19: 1.2–1.5 s on the reference emulator, 3.7 s first start after install.
* **Do.** Profile start-up (`flutter run --profile --trace-startup`); defer non-visible work (sync, websocket, image cache warm-up)
  until after the first frame; check the database open and the first query; consider a baseline profile for ART.
* **Acceptance.** `adb shell am start -W` TotalTime ≤ 700 ms p50 over 10 runs on a mid-range phone; ≤ 1.5 s on profile A's emulator.

## P5-05 — The website — Size M
* **Order.** Needs: P3-07 [d].
* **Not now (owner, 2026-10-21: "let's not worry about website, name and things like that").** Start only when the owner asks.
* **Do.** Static site in `website/` (built from `docs/guides/`), hosted on GitHub Pages with the owner's domain (D-9): landing (what
  Encore is, screenshots, "free, no subscription"), Install in 3 steps (Linux install video link, the command, the wizard), Download
  (APK + checksum + "how to install an APK"), FAQ (Docker never needed; what hardware; away from home; privacy), **Where songs come
  from** (plain: your files, and YouTube for the rest; switch it off; your responsibility where you live), Privacy, Terms, Source code.
  Final product name decided first (D-5).
* **Acceptance.** A person who never used Encore follows only the website and gets a friend listening (P3-07 + one real outsider).

## P5-06 — Go public — Size S
* **Order.** Needs: P5-03 [d], P5-09 [d], P0-10 [i], P0-12 [i], P3-09 [i]. Why: P5-09 is the owner's step of starting the third deep review; P5-06 itself says v1.0.0 comes after P5-03; the licence inventory, the scrub of documents that name the owner's machines (README) and the last security review (P3-09: "before P5") must hold before the repository and the images become public..
* **Before it (2026-11-03).** The third ultrareview (`/code-review ultra`) and the scrub list of `docs/README.md` (the plan documents that still name the owner's own machines).
* **Do.** Repo public (GPL-3.0), images public, first release `v0.9.0` (beta) then `v1.0.0` after P5-03; announce where the owner wants.
* **Reports from people the owner does not know (ADR-R36).** Issues switched on; the owner's GitHub notification e-mail for new issues checked (it
  is on by default for the owner of a repository); "private vulnerability reporting" switched on (`SECURITY.md` already asks for it); the issue form
  asks for the app's technical details (Diagnostics > Copy report); if an in-app report or message to the owner exists by then (R35, P4-13), it gets one more
  line: "A bug in Encore itself: open an issue at github.com/<owner>/encore/issues".
* **Acceptance.** `gitleaks` clean on the full history; no homelab or personal data anywhere (`git grep -iE "192\.168\.|tail[0-9a-f]{6}|appayiip"` reviewed).

## P5-07 — How a friend installs the APK from GitHub (the install guide; no developer account) — Size S
* **Order.** Needs: P5-01 [d].
* **Decided (owner, 2026-11-04, D-56; reaffirms D-17).** Encore is distributed on **GitHub only**: no Play Store, no developer account of Google's or Apple's, nothing paid. The account part of this task is gone (I had moved it up on 2026-11-03: that went against D-17); the install guide stays, because the first friend needs it.
* **Why.** `../26` H44: installing an APK is hard for ordinary people ("Install unknown apps" per browser or messenger, Play Protect warnings, different screens per brand). H43: Google's developer verification (since 30 Sep 2026 in some countries, worldwide in 2027) means an app from an unregistered developer installs on a certified phone only through Android's "advanced" flow or a cable. D-17's own trigger stays: if that rule blocks the friends' installs, revisit (a free limited-distribution account covers 20 devices).
* **Do.** Write the install guide with screenshots for Samsung, Xiaomi and Pixel ("Install unknown apps", Play Protect, and Android's advanced flow for an unregistered app), linked from the invite page and the GitHub Release notes. Evaluate Obtainium (installs and updates from GitHub Releases) as a channel. No store listing, no registration.
* **Acceptance.** A non-technical person installs the APK from the guide on a Samsung and a Xiaomi without help.

## P5-08 — What's new and in-app help — Size S
* **Order.** Needs: none.
* **Why.** `../27` §1.
* **Do.** After an update, one card "What's new" with 3 lines from the release notes; Settings → Help: short answers (how songs reach
  you, away from home, downloads, Jams, privacy) linking to the guides; "Report a problem" (P4-13) from the same place.
* **Acceptance.** The help answers are written in the screen checklist's plain words (`../07` §10) and reviewed by the owner.

## P5-09 — Start Claude's deep security review before going public (owner) — Size S
* **Order.** Needs: P5-03 [d].
* **Owner's step (D-59).** One command typed by him (`/code-review ultra`, billed) on the branch Claude prepares, before the code and the images become public. Claude tells him the exact command when it is time. Today: nothing to do yet.
* **Acceptance.** The third review ran and every finding is fixed or accepted in writing.
* **Size.** S (his time, not counted).
