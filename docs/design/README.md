# Design

The design of Encore, drawn before it is built (owner, 2026-10-24: *"we have not started with a design in Figma or so; make a design for all pages, and the future ones"*). The drawings are self-contained HTML files, so they are versioned with the code and open in any browser.

| File | What |
|------|------|
| [00-screen-inventory.md](00-screen-inventory.md) | **Every screen**, today and later, with the states each must show and the layout classes (phone C, browser X, TV T). A screen or a state that is not here is not designed |
| [directions/index.html](directions/index.html) | **The page "Encore Design Choice"** the owner is shown: how to read the drawings against the app (the known differences), one card per drawing file with its frame count, what was decided. The same page is published as an artifact; this file is its source |
| [directions/a-cover-led.html](directions/a-cover-led.html) | **The drawing**: the four anchor screens (Home, Now playing, Search and Artist, Welcome and Your server) in the cover-led direction, Spotify-like colours and layout. Open it in a browser; every view has a link. (Two other directions were drawn and **dropped by the owner on 2026-10-24**; they are in the git history only) |
| [history/README.md#design-04-review-2026-10-30](../history/README.md#design-04-review-2026-10-30) | **The review of what is built against what is drawn** (the F46 revision pass): for each screen, built / part / no / parked, which frames are stale, and the order to redraw. D-43 then made the built screen the reference |
| [directions/screens-first-run-and-settings.html](directions/screens-first-run-and-settings.html), [screens-library-and-browse.html](directions/screens-library-and-browse.html), [screens-player-together-and-more.html](directions/screens-player-together-and-more.html), [screens-server-and-browser.html](directions/screens-server-and-browser.html) | The other four drawing files (first run and settings; library and browse; player, together and more; the server's pages W-02 to W-08). History wherever the app already has the screen (D-43) |
| [history/README.md#design-03-owner-review-2026-10-24](../history/README.md#design-03-owner-review-2026-10-24) | **The owner's review of the three drawings, one verdict per point**: copy Spotify's familiar screens (Now playing), personality on first-run screens, no owned/catalogue marker, a neutral server name, the UI follows the server's capabilities, opt-in taste comparison |

**The owner's two pages** (claude.ai artifacts, private to him; the first has its source in `directions/index.html`, the second is a report with four screen clips): the design page "Encore Design Choice", (a private claude.ai artifact, not public), and the QA report of the phone walk and the backend review of 30 to 31 Oct 2026, (a private claude.ai artifact, not public) (`../history/README.md#qa-ui-2026-10-31`).

**Where a drawing and the app disagree, the app wins** (D-43); `directions/index.html` lists the known differences. **Parked** (D-18, D-48 a): TV, tablet and car frames and the web player (W-06). The files keep them as history; a new page is drawn at the phone (C) and PC (X) classes only.

Rules that every screen follows are in `../11` ADR-R42 (layout classes, D-pad, right-to-left, text at 200 %, no words in pictures) and `../16` (personality). The states come from `../31` to `../34`.
