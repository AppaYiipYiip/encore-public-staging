# Design

The design of Encore, drawn before it is built (owner, 2026-10-24: *"we have not started with a design in Figma or so; make a design for all pages, and the future ones"*). The drawings are self-contained HTML files, so they are versioned with the code and open in any browser.

| File | What |
|------|------|
| [00-screen-inventory.md](00-screen-inventory.md) | **Every screen**, today and later, with the states each must show and the layout classes (phone C, browser X, TV T). A screen or a state that is not here is not designed |
| [01-brief-three-directions.md](01-brief-three-directions.md) | The brief the three directions were drawn from |
| [directions/](directions/) | The three drawings of the four anchor screens (Home, Now playing, Search and Artist, Welcome and Your server): `a-cover-led.html`, `b-quiet-editorial.html`, `c-warm-home.html` |
| [02-direction-choice.md](02-direction-choice.md) | **The choice**: A as the base, B's state marks and 200 % rules everywhere, C only for first run and identity; three tabs; one pattern for "the server does not answer" |
| [03-owner-review-2026-10-24.md](03-owner-review-2026-10-24.md) | **The owner's review of the three drawings, one verdict per point**: copy Spotify's familiar screens (Now playing), personality on first-run screens, no owned/catalogue marker, a neutral server name, the UI follows the server's capabilities, opt-in taste comparison |

Rules that every screen follows are in `../11` ADR-R42 (layout classes, D-pad, right-to-left, text at 200 %, no words in pictures) and `../16` (personality). The states come from `../31` to `../34`.
