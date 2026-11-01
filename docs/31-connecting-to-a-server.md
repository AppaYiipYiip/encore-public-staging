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
| CN-1 | `none` (no network) | airplane mode, no Wi-Fi and no data | after **4 s** a slim strip above the player: "You're offline. Downloaded music still plays." **(D-45, 2026-10-31: said once per outage, for 5 s or until the cross; not again until everything has worked for 10 s; no internet and a server that does not answer are one outage and one sentence)**; downloaded songs play, other rows are greyed (`33`). **`07` §5 says "no banner": a conflict, O-5** | Built | `app/providers.dart` `NetworkKind`; `app/connection.dart`; `features/common/connection_banner.dart` | `connection_test.dart`, `connection_banner_test.dart` |
| CN-2 | `wifi` | joined a Wi-Fi network (any, the name is never read: ADR-R40 D4) | nothing | Built | same | none |
| CN-3 | `mobile` | no Wi-Fi, mobile data | the "Wi-Fi only" download setting may hold downloads ("Waiting for Wi-Fi") | Built | same; downloads | `AUDIT` F3 walk |
| CN-4 | changed (any of the above to another) | the phone moves, switches network, a captive portal ends | the address race starts again (CN-12); nothing is shown unless it fails | Built | `EndpointResolver` re-resolves on network change | `endpoint_resolver_test.dart` |
| CN-4b | **`mobile` or `wifi` but nothing answers** (4G radio on with no data, a Wi-Fi with a sign-in page, the server is off) | the phone has a network and a look at every address found none that answers (`EndpointResolver.isKnownUnreachable`; `false` before the first look and after the network changed) | the same strip and the same sentence as CN-1 (one outage); for the player this is **offline**: songs that are not downloaded are not tried (`33` PB-F4, PB-F5, PB-F7b); before a song is refused the server is asked once (not again for 5 s) | **Decided (D-46, 2026-10-31); in the phone batch, not on `main` yet: marked built when it lands** | `app/playback_providers.dart` `canReachServerNow`; `endpoint_resolver.dart`; `playback_engine.dart` `_canReachNow` | `can_reach_server_test.dart`, `endpoint_resolver_test.dart`, engine `the server was found out of reach and is back` |

## 3. One address of one server (question 2): the states of a single candidate

A server has a list of candidate addresses (a typed one, the Tailscale/Funnel one, later the ones the server tells the phone). Each candidate is in one state.

| ID | State | Caused by | What the person sees | Status | Where | Test |
|----|-------|-----------|----------------------|--------|-------|------|
| CN-5 | `untried` | the list was just made or the network changed | nothing | Built | `endpoint_resolver.dart` | `endpoint_resolver_test.dart` |
| CN-6 | `probing` | the race reached it (the first at once, later ones 350 ms apart each) | "Looking for your server…" only while nothing else works yet | Built | `endpoint_resolver.dart`; the probe is now the public identity question (CN-9), **no login**; the old probe (a Subsonic `ping` carrying the login token, S2) is used only when verification is switched off, in tests | `endpoint_resolver_test.dart` |
| CN-7 | `reachable` | the probe answered, or answered "login refused" (counted as "this is the server") | nothing | Built | `session.dart` probe | same |
| CN-8 | `unreachable` | no answer within 4 s (3 s to connect), refused, DNS failure, TLS not trusted | nothing alone; if all candidates are in this state, CN-14 | Built | same | same |
| CN-9 | `asking` | the probe is the public `GET /info?challenge=<fresh nonce>`, **no login, no token, no header of ours**; 24 random bytes a time, a recorded answer is useless the second time | nothing | **Built** (P2-19 slice A) | `server_identity.dart` `ServerIdentityProbe.check` | `server_identity_test.dart` (the question carries a fresh challenge and nothing else) |
| CN-10 | `verified` | the answer's key hashes to the id (26 base32 characters) and the signature over `encore.info.v1\n<id>\n<my nonce>` verifies; with a pinned id it must also be that id. **The id, the message and the signature agree byte for byte with the Python server** (a vector made by it) | nothing | **Built** | `verifyServerAnswer`, `serverIdForKey` | `server_identity_test.dart`; server `test_the_key_made_from_a_known_seed_gives_the_id_and_signature_the_phone_expects` |
| CN-11 | `wrong key` | it answers, but with another key, a signature that does not verify, a copied id with its own key, an old recorded answer, or **no key where one is pinned (it cannot downgrade)** | the typed form says "Another server answers at <host>, not the one you know."; elsewhere the strip says "Can't reach your server." (a specific line for the strip is open, O-6). It is never sent a login and is not used until the network changes | **Built** | `server_identity.dart`; `ServerSetupService.check` | `server_identity_test.dart`, `session_verification_test.dart` (an impostor at the saved address is asked and never sent anything else) |
| CN-11b | `legacy` | an older Encore server with no key, or a plain music server: its unauthenticated Subsonic `ping` is answered with an error envelope ("missing parameter: 'u'", checked on Navidrome 0.64.2) | nothing; used as before, the key is learned the first time the server can give one. **Never accepted for a server whose key is pinned** | **Built** | `ServerIdentityProbe._legacyMusicServer` | `server_identity_test.dart` (a plain music server is recognised without sending it any login) |
| CN-11c | `first contact` | a server row saved before keys has no id; the first time its server proves one the phone pins it (trust on first use), kept in `capabilitiesJson.serverId` (no schema change). **A join link now carries the id** (`?id=`), so a new row is verified from the first contact; a typed address learns it at the first check | nothing | **Built** | `ServerSession.create` `_pinServerId`; `ServerSetupService.save(serverId:)` | `session_verification_test.dart` (learns the key the first time; once learned, the key counts) |

**Rule that follows from S2 (Built, P2-19 slice A):** a login, a token, a signed address or a query credential is sent **only** to a candidate in `verified` (or `legacy`, which gets the credentials it always had but no probe with them). Every request, stream and cover is built from one address, `endpoints.currentUrl`; with verification on it is only ever an address that proved itself, and otherwise `unverified.invalid`, a name that can never be reached (`EndpointResolver.requireVerified`, `unverifiedUrl`). The first race has to finish before the first request leaves the phone (a round trip: measured in the slice A pull request), a race that finds nothing takes the last good address back, and a **change of network** (`networkKindProvider`) invalidates it at once and runs the race again. Tests: `endpoint_resolver_test.dart` (the gate), `session_verification_test.dart` (nothing but the question reaches an impostor).

## 4. Choosing among the addresses: the race

| ID | Rule | Status | Where | Test |
|----|------|--------|-------|------|
| CN-12 | Start order: the list order (the first typed address first); each later candidate starts 350 ms after the previous unless one already won; the **first success wins**; the list order breaks ties. Requests use `currentUrl`: the last winner **that proved itself**, or `unverified.invalid` before any race has finished, after one that found nothing, and after a change of network | Built | `EndpointResolver._resolve`, `currentUrl`, `invalidate` | `endpoint_resolver_test.dart` |
| CN-13 | Re-race triggers: app start, **a change of network kind (it also invalidates, CN-12)**, 2 failed requests in a row (`reportFailure`), "try again"; every sync run starts with a race. A silent Wi-Fi to Wi-Fi switch that sends no event is only caught at the next sync run's race (O-7) | Built | `endpoint_resolver.dart`; `app/app.dart` listener | `endpoint_resolver_test.dart` |
| CN-14 | No candidate answered, **or the only ones that answered gave another key (CN-11)**: nothing is sent to any address (`currentUrl` is the unreachable `unverified.invalid`; the shown address, `current`, is left as it was), and after the 4 s grace the strip says "Can't reach your server." with a **Try again** button (it runs the race again); the live connection retries after 1, 2, 4 … 30 s | Built; walked on a phone with an impostor as the only answer (`evidence/b03`) | `app/connection.dart` (`serverUnreachable`), `connection_banner.dart`; `encore_live.dart` `firstRetry`/`longestRetry` | `connection_test.dart`, `encore_live_test.dart`; `evidence/b03` |
| CN-15 | The list is refreshed from `GET /encore/api/v1/server` once an address has proved itself and whenever another one wins the race; an address the server names is **added beside the person's own** (`capabilitiesJson.learnedAddresses`, labelled Home or Away), never in their typed list, refused if it is plain http on the internet, ignored if the answer names another key; it is only used after it has proved itself. Invitations take the https one automatically (`invitationAddress`), so the owner no longer types it. Demoting a home address that keeps failing on other networks is open (O-2) | **Built** (P2-19 slice A) | `ServerSession.refreshAddresses`, `learnedAddresses`; `encore_api.dart` `server()` | `session_verification_test.dart` (the addresses the server tells the phone) |
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
| CN-24 | the login itself is refused (password changed, account removed, account locked) | `AuthFailure` from sync, or from something the person tapped | a **quiet card on Home** ("Sign in again"); a tapped song or action opens the sign-in prompt once; downloads, queue and likes are kept; a correct password clears it. **The live channel's device sign-in does not retry a refused password for 15 minutes** (before S1, twenty wrong tries locked the account and a second phone left on an old password did exactly that, `evidence/b05`; since S1 a wrong password only slows the server's answer and never locks, and the phone still stops asking so that it does not keep the server busy) | Built (P2-18, J-21; the retry limit 2026-10-24) | `features/auth/login_problem.dart`, `encore_device.dart` | `login_problem_test.dart`, `CN-24: a password the server refused is not tried again for a while (twenty wrong tries lock the account)` |
| CN-25 | the account is locked (only the owner locks an account: a wrong password never does, AUDIT B2) | server | the server's sentence: "This account is locked. Ask the owner of this server to unlock it." | Built | `api.py` login and `get_principal` | `test_wrong_passwords_never_lock_an_account_or_sign_out_its_phones`, `test_public_edge.py` |
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
| CN-34 | an address that answers with another key (CN-11) | the typed form and the join screen say it ("Another server answers at … not the one you know.", "This is not the server that invited you. Ask for a new invitation.") | a specific line in the strip (O-6) | Built (forms) / Open (strip) | `join_invitation_test.dart`, `server_identity_test.dart` |
| CN-35 | the server restarts while the phone is connected | the live connection drops and returns by itself within 45 s without a tap | same | Built | `evidence/b01` (walked, not an automated test) |

## 7. Debts and findings this document makes visible

* **S2 (`AUDIT`): fixed in P2-19 slice A** (PR #11): credentials no longer go to any candidate before it has proved itself (CN-6, CN-9 to CN-11c, the rule under CN-11c).
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
| O-6 | The strip says "Can't reach your server." for a wrong key too; should it say "Another server answers at this address"? (Proposal: yes, once, with the address's name.) | **Decided 2026-10-23: as proposed** |
| O-7 | A Wi-Fi to Wi-Fi switch that sends no event is caught only at the next sync run's race. Re-verify when the app comes to the front if the last proof is older than a minute? (Proposal: yes.) | **Decided 2026-10-23: as proposed** |
| O-8 | **Learned addresses are invisible** (`evidence/b03` F-2): "Your server" lists only what the person typed, but the phone also uses the addresses its server told it (CN-15), so deleting a typed address does not stop the phone using the same one and nothing says so. Show them under "From your server" (Home, Away) with a way to say *don't use this one*; a deleted typed address that the server also names is shown there, not silently kept. | **Decided 2026-10-24: as proposed** (task: P2-19, with slice B's first screen) |
| O-9 | **Look-ups that carry no login still go to a saved address that has not proved itself** (`evidence/b03` F-1): the "play any song" service look-up and the Jam hub look-up build their addresses from the saved list. On a plain (non-Encore) server the instant-play client then sends `/api/play` with the Subsonic token to that address. Rule: every address a phone talks to has first proved who it is; where a plain server cannot prove it, say so in this table. The look-ups use `endpoints.currentUrl` (nothing is sent while it is unverified) and, for an Encore server, are replaced by asking the server (ADR-R38). | **Decided 2026-10-24: as proposed** (task: P2-19 slice A follow-up, small PR after #11) |
