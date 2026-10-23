# P6 — Later (after the first public version; each needs a decision first)

Jam, friend activity, recommendations, the quality tier and Year in Music are **not** here: the owner put them in the first version
(phase P4, `P4-full-feature-set.md`).

| Item | What must be true first | Notes |
|------|-------------------------|-------|
| **Web/desktop client** | Server API stable (P2/P3); device tokens; **the phone's direct calls to outside services moved to the server (ADR-R38: P2-12 catalogue and previews, P2-14 lyrics, the new-release check, covers); signed addresses for previews and covers** | Flutter web/desktop over the same API; the gateway already serves streams (signed addresses, Range); resume-anywhere and single-device playback already work across clients. A browser cannot call Deezer or LRCLIB itself and cannot run YouTube extraction: it never will, the server does. Unchecked: whether Flutter web can load outside cover pictures, and web versions of the phone-only parts (files, local database, secure storage, background work) |
| **iOS** | Owner decision; Apple developer account | Sideloading is not possible for most iPhone users; needs the App Store or TestFlight |
| **Casting (Chromecast, TV speakers)** | Owner decision | Encore devices are in v1 (P4-07); casting to non-Encore speakers is later |
| **On-device extraction fallback** | Experiment X-3 | Only if server-side resolution gets blocked for many Hosts |
| **Localisation** | Strings in one file (prepared in P1-12) | French and Arabic first (right-to-left), then Spanish |
| **"Encore OS" image** | Evidence that Hosts struggle to install Linux | Flash-and-boot like Home Assistant OS; large maintenance cost |
| **Audiobooks / podcasts** | Owner decision | — |
