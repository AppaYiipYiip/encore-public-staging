# 31 — Connecting to a server: the network, the address, who answers, signed in or not

The state tables for everything between "the phone starts" and "the phone may ask its server for music". Written 2026-10-23 from the code (files named in the
**Where** column) and from the decisions in `11` ADR-R40 (the key as identity, the server's own addresses). Joining a server and the account's life are in `32`;
playing and what happens when the connection breaks while playing are in `33`.

**How to read the tables.** Every row has an ID (`CN-n`), what causes it, what the person sees, a **Status** and a **Test**.
**Built** = the code does it and I read the code. **Designed** = decided in the plan, not in the code. **Open** = nobody has decided; collected at the end.
A **Test** of "none" is a debt, not a decision. A change that touches one of these states updates its row in the same pull request (`30` §0).

## 1. Three questions, asked in this order

A phone with a saved server asks, at every start and after every network change: **(1)** is there a network at all? **(2)** which address is my server
at, and is it really my server? **(3)** am I signed in there? Each has its own states below. The screen shows the **first** answer that is "no": a person
with no network is never told "sign in again".

## 2. The network (question 1)

| ID | State | Caused by | What the person sees | Status | Where | Test |
|----|-------|-----------|----------------------|--------|-------|------|
| CN-1 | `none` (no network) | airplane mode, no Wi-Fi and no data | after **4 s** a slim strip above the player: "You're offline. Downloaded music still plays." (it goes away at once); downloaded songs play, other rows are greyed (`33`). **`07` §5 says "no banner": a conflict, O-5** | Built | `app/providers.dart` `NetworkKind`; `app/connection.dart`; `features/common/connection_banner.dart` | `connection_test.dart`, `connection_banner_test.dart` |
| CN-2 | `wifi` | joined a Wi-Fi network (any, the name is never read: ADR-R40 D4) | nothing | Built | same | none |
| CN-3 | `mobile` | no Wi-Fi, mobile data | the "Wi-Fi only" download setting may hold downloads ("Waiting for Wi-Fi") | Built | same; downloads | `AUDIT` F3 walk |
| CN-4 | changed (any of the above to another) | the phone moves, switches network, a captive portal ends | the address race starts again (CN-12); nothing is shown unless it fails | Built | `EndpointResolver` re-resolves on network change | `endpoint_resolver_test.dart` |

## 3. One address of one server (question 2): the states of a single candidate

A server has a list of candidate addresses (a typed one, the Tailscale/Funnel one, later the ones the server tells the phone). Each candidate is in one state.

| ID | State | Caused by | What the person sees | Status | Where | Test |
|----|-------|-----------|----------------------|--------|-------|------|
| CN-5 | `untried` | the list was just made or the network changed | nothing | Built | `endpoint_resolver.dart` | `endpoint_resolver_test.dart` |
| CN-6 | `probing` | the race reached it (the first at once, later ones 350 ms apart each) | "Looking for your server…" only while nothing else works yet | Built | same; probe = Subsonic `ping` with the person's login token (**the problem, S2**) | same |
| CN-7 | `reachable` | the probe answered, or answered "login refused" (counted as "this is the server") | nothing | Built | `session.dart` probe | same |
| CN-8 | `unreachable` | no answer within 4 s (3 s to connect), refused, DNS failure, TLS not trusted | nothing alone; if all candidates are in this state, CN-14 | Built | same | same |
| CN-9 | `asking` | **Designed:** the probe is the public `GET /info?challenge=<fresh nonce>`, **no login, no token** | nothing | Designed (ADR-R40 D1) | planned: `identity.py` is the server half (built, `test_identity.py`) | server: 32 tests; app: none yet |
| CN-10 | `verified` | **Designed:** the answer's key hashes to the id this phone has for the server, and the signature over the id and the nonce verifies | nothing | Designed | `identity.verify` (server module, same check for the app) | `test_identity.py` (the check), app none |
| CN-11 | `wrong key` | **Designed:** it answers, but with another key or no valid signature (a copied id, a stranger at a recycled address) | "Another server answers at this address, not yours." Never sent a login, never used again until the network changes | Designed | none yet | `test_somebody_who_copies_the_id_cannot_sign_for_it` (server side of the check) |
| CN-11b | `legacy` | **Designed:** an old server that sends no id: its unauthenticated Subsonic `ping` answers an error envelope ("missing parameter: 'u'") | nothing; used as today, the id is learned the first time the server can give one | Designed | checked on the dev VM's Navidrome 0.64.2 (ADR-R40) | none |
| CN-11c | `first contact` | **Designed:** a server row saved before P2-19 slice A has no id yet (only rows on the emulators exist); the first time its server answers with an id, the phone pins it (trust on first use). **From then on a join or pairing link carries the id**, so a new row is verified from the first contact | nothing | Designed (ADR-R40) | none | none |

**Rule that follows from S2 (Designed, not yet true in the code):** a login, a token, a signed address or a query credential is sent **only** to a candidate in
`verified` (or `legacy`, which gets the credentials it always had but no probe with them). Today the first candidate is used for every request before any probe has
run (`session.dart`: `baseUrl: () => endpoints.currentUrl`, and `auth: client.authQuery` signs the ordinary Encore calls with a token made from the stored password).

## 4. Choosing among the addresses: the race

| ID | Rule | Status | Where | Test |
|----|------|--------|-------|------|
| CN-12 | Start order: the list order (the first typed address first); each later candidate starts 350 ms after the previous unless one already won; the **first success wins**; the list order breaks ties. Requests use `current`: the last winner, or the first address before any race has finished | Built | `EndpointResolver._resolve`, `current` | `endpoint_resolver_test.dart` |
| CN-13 | Re-race triggers: app start, network change (CN-4), 2 failed requests in a row (`reportFailure`), "try again" | Built | same | same |
| CN-14 | No candidate answered: `current` is left as it was (requests still go there), and after the 4 s grace the strip says "Can't reach your server." with a **Try again** button (it runs the race again); the live connection retries after 1, 2, 4 … 30 s | Built | `app/connection.dart` (`serverUnreachable`), `connection_banner.dart`; `encore_live.dart` `firstRetry`/`longestRetry` | `connection_test.dart`, `encore_live_test.dart` |
| CN-15 | **Designed:** the list is refreshed from `GET /encore/api/v1/server` after every sign-in and when an address stops answering; an address the server names is added, a home address that fails verification on 3 networks in a row is moved to the end | Designed (ADR-R40 D3); the "3 networks" figure is **Open** (O-2) | `/server` is built on the server | `test_server_hands_out_the_home_and_the_away_address_it_was_told` (server) |
| CN-16 | **Designed:** discovery (`_encore._tcp` from the host's avahi) adds candidates it finds **by the id they claim**; a claimed id is worth nothing until CN-10 | Designed (slice C) | none | none |
| CN-17 | An address that is `http` and not a home address (public name or address) is refused when typed: "Servers reached over the internet must use https://" | Built | `core/network_policy.dart` `cleartextProblem`; `.local`, `.lan`, `.home`, `.ts.net` and private ranges count as home | `network_policy_test.dart` (the home test), `server_url_test.dart` |

## 5. Signed in or not (question 3), per server on this phone

The phone keeps, per server, in the secure store: the person's **password** (still: `D`-debt below), and a **device token** (`encore.device.<n>`), plus the
server profile row in its database (name, addresses, capabilities).

| ID | State | Caused by | What the person sees | Status | Where | Test |
|----|-------|-----------|----------------------|--------|-------|------|
| CN-20 | no server saved | first run | the first screen (`15` A1; today it asks for an address first, `evidence/b02`) | Built (order is wrong, P2-19 slice B) | `connect_screen.dart`, `join_screen.dart` | `join_invitation_test.dart` |
| CN-21 | signed in, token saved | normal | Home | Built | `EncoreDevice.token` reuses the saved token until the server refuses it | none |
| CN-22 | token missing or unreadable | secure store cleared, first start after a join | nothing: the phone signs in once with the saved password and keeps the new token (**one new device in the person's list**) | Built | `encore_device.dart` | none |
| CN-23 | token refused on the live channel (revoked, account locked, all devices signed out by a password change) | server says 401 | the saved token is forgotten and the next try signs in again with the saved password | Built (`tokenRefused: device.forget`) | `encore_live.dart` | `encore_live_test.dart` |
| CN-24 | the login itself is refused (password changed, account removed, account locked) | `AuthFailure` from sync, or from something the person tapped | a **quiet card on Home** ("Sign in again"); a tapped song or action opens the sign-in prompt once; downloads, queue and likes are kept; a correct password clears it | Built (P2-18, J-21) | `features/auth/login_problem.dart` | `login_problem_test.dart` |
| CN-25 | the account is locked (20 wrong passwords, or the owner locked it) | server | the server's sentence: "This account is locked. Ask the owner of this server to unlock it." | Built | `api.py` login and `get_principal` | `test_twenty_wrong_passwords_lock_the_account_until_the_owner_unlocks_it` |
| CN-26 | too many tries | 5 a minute per name, 20 per address | a wait that says how long | Built | `accounts.Limiter` | `test_five_tries_a_minute_for_one_name_and_then_a_wait_that_says_how_long` |
| CN-27 | the server's API is newer than this app can speak (`apiVersion` major unknown) | server upgrade | "Update Encore" (or "Ask Riley to update the server") | Designed (`17` §1) | none | none |
| CN-28 | signed out on purpose | the person | **everything of that server on the phone is deleted, downloads included**, after a confirmation that says how much | Built | `features/settings/sign_out.dart` | none |

## 6. What the person sees when it does not work (the failure words, in one place)

| ID | Situation | Words today | Words wanted | Status | Test |
|----|-----------|-------------|--------------|--------|------|
| CN-30 | server reachable, login wrong (typed form) | "The server is there, but the username or password was not accepted." | same | Built | none |
| CN-31 | no candidate reachable (typed form) | "Can't reach <host>. Are you on the same Wi-Fi?" | "Can't reach your server from here" + why when known: away access is off, or this network blocks it | Built (first half) / Designed (second) | none |
| CN-32 | an invitation link while the phone is still waking up | "Reaching the server…" and 3 retries (2, 4, 8 s) before "Can't reach" | same | Built | `join_invitation_test.dart` |
| CN-33 | an invitation for a server this phone already has an account on | says so | same | Built | `invite_link_test.dart` |
| CN-34 | an address that answers with another key (CN-11) | (not possible today: any answer is believed) | "Another server answers at this address, not yours." | Designed | none |
| CN-35 | the server restarts while the phone is connected | the live connection drops and returns by itself within 45 s without a tap | same | Built | `evidence/b01` (walked, not an automated test) |

## 7. Debts and findings this document makes visible

* **S2 (`AUDIT`):** credentials go to every candidate before any check (CN-6, the rule under CN-11b). Fixed by P2-19 slice A.
* **D-1:** the phone still keeps the person's **password** and signs ordinary Encore calls with a salted-md5 token **in the URL** (`30` §B, C9: tokens belong in a header). Only the live channel uses the device token. Task: P3-03 / P2-18 follow-up; until then the address check matters even more.
* **D-2:** CN-21, CN-22 have no test; the sign-out (CN-28) has no test.
* **D-3:** the first screen still leads with an address form (CN-20).

## 8. Open (to decide; the engineering ones I decide, the product ones go to the owner in one batch)

| ID | Question | Who |
|----|----------|-----|
| O-1 | When the server tells the phone a new home address, does the phone drop an old home address immediately or keep it as a candidate? (proposal: keep, last in the order, drop after 30 days unused) | **Decided 2026-10-23: as proposed** |
| O-2 | How many networks in a row may a home address fail verification before it is demoted (CN-15)? (proposal: 3) | **Decided 2026-10-23: as proposed** |
| O-3 | Two servers answer with two different known ids on one network: which does the phone use? (proposal: the one it used last; the other is offered as "Switch to …") | product |
| O-4 | Is a phone allowed to stay signed in for ever, or does a token expire (30/90/180 days)? Today it never expires | product |
| O-5 | **A conflict between documents:** `07` §5 and P1-09 say "offline: no banner"; the app shows the slim strip (CN-1, CN-14) the owner asked for on 2026-10-17. Keep the strip (my proposal: yes, it is one line, after 4 s, gone at once) and correct `07`? | product |
