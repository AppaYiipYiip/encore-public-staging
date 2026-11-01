# 32 — Accounts, joining a server, and devices: every way in, every state

Written 2026-10-23 from the server (`accounts.py`, `auth.py`, `api.py`, `setup.py`) and the app (`join_screen.dart`, `connect_screen.dart`, `encore_device.dart`,
`login_problem.dart`, `profiles/`), and from the decisions in `11` ADR-R40. How the phone finds the server and proves who answers is `31`; this document starts
where the phone has an address it trusts. Same reading rules as `31`: **Built** (I read the code), **Designed** (in the plan, not in the code), **Open**;
a Test of "none" is a debt. A change to one of these states updates its row in the same pull request.

## 1. Words

* **Person**: one human's account on one server (`person` row); has a role, **owner** or **member**. At least one owner always exists.
* **Device**: one phone, tablet or browser signed in as a person (`device` row), with its own token. A person has many devices.
* **Profile** (on the phone): somebody who has signed in on this phone; the picker "Who's listening?" switches between them without a password (`33`: downloads are per profile).
* **Invitation**: a single-use code (7 days) an owner makes so one new person can create an account.

## 2. Every way an account comes to exist

| ID | Way | Who starts it | What is needed | Result | Status | Where | Test |
|----|-----|---------------|----------------|--------|--------|-------|------|
| AC-1 | **The installer's owner** | the Host, once, in the terminal | a username and a password (8 to 128 characters) | the music server's administrator and the owner's account exist; **the first person to sign in becomes the owner** | Built | `setup.py`, `install.sh` | `test_setup.py` |
| AC-2 | **An invitation** | an owner makes it; the new person opens its link | the link (or code) | the new person chooses a name and a password; the music server makes the account, this server makes the person and a device, the invitation is used up (all or nothing) | Built | `accounts.py` `join` | `test_joining_makes_the_account_the_person_and_a_device_and_uses_the_invitation_up` |
| AC-3 | **An owner-making invitation** | an owner chooses "Another owner" when inviting | same | the same, with role owner | Built | `create_invite(role=...)` | `test_an_invitation_may_make_another_owner` |
| AC-4 | **A login that already exists in the music server** | the person, with that login | the music server's username and password | the first sign-in makes the person: **owner if they are the first person on the server or the music server calls them an administrator, else member** | Built | `api.py` `login`, `get_principal`, `library.ensure_person` | `test_the_music_servers_login_works_as_it_does_today` |
| AC-5 | **A migrated old install** | the owner, once | the old accounts in the music server | every music-server account becomes a person with its likes and playlists | Built (server endpoint); the app's "move" banner is open | `migration.py` | `test_migration.py` |
| AC-6 | **A password-reset link** (not a new account: a new door into one) | an owner, for a person who forgot | the link | the person chooses a new password; **all their devices are signed out**, the lock is cleared, one new device is issued | Built (server); **no screen in the app opens the link** | `accounts.py` `create_reset`, `reset_password`; `POST /auth/reset` | `test_a_forgotten_password_is_reset_with_a_link_the_owner_sends` |
| AC-7 | **A pairing link for the owner's own phone** | the installer, or `encore pair` | scanning or opening it | signed in as the owner with no typing and no password (single use, 10 minutes, never in a log) | Designed (ADR-R40 D7, P2-19 slice B) | none | none |
| AC-8 | **Quick Connect** | a phone that found the server shows a 6-digit code | a signed-in device approves the code | a new device (and, for a new person, an account) with no password dictated | Designed (ADR-R40 D5, slice D) | none | none |
| AC-9 | **Somebody added on a shared device** | a person on a phone or tablet that already has an account on the server | "Add someone" > sign in, or an invitation | a profile on this device (the account is made elsewhere by AC-2 or exists) | Built, first slice | `features/profiles/` | `profiles_test.dart`, `device_profiles_test.dart` |
| AC-10 | **Sign in with Google / Spotify / another service** | — | — | **Not offered, on purpose**: no account of a person's on the server, ever (`30` §B, ADR-R2) | Decided | — | — |

The username rule: 3 to 32 letters, digits, dots, dashes, underscores, starting and ending with a letter or digit, lower-cased; the names `admin`, `administrator`, `root`,
`encore`, `encore-admin`, `navidrome`, `system`, `owner`, `guest`, `everyone` are not available. A password may not equal the name.

## 3. The states of an invitation

| ID | State | Caused by | What the person sees | Status | Where | Test |
|----|-------|-----------|----------------------|--------|-------|------|
| IV-1 | **open** | an owner made it; the code was shown **once**; only its hash is stored | the link, the QR, and who it is for ("for Sara") in the owner's list | Built | `accounts.create_invite` (7 days) | `test_the_owner_makes_an_invitation_and_the_code_is_shown_once` |
| IV-2 | **checked** | the new phone asks "who invited me?" before a name is chosen | "<Name> invited you" | Built | `GET /invites/check` (20 a minute per address) | `test_the_join_screen_can_say_who_invited_before_a_name_is_chosen` |
| IV-3 | **used** | a join succeeded | the owner's list shows who used it | Built | `invite.used_by` | `test_joining_makes_the_account_the_person_and_a_device_and_uses_the_invitation_up` |
| IV-4 | **expired** (after 7 days) or **revoked** by the owner or **already used** | time, the owner, an earlier join | one sentence for all three, on purpose: "That invitation is not valid any more. Ask for a new one." | Built | `_open_invite` | `test_an_expired_or_revoked_invitation_does_not_work` |
| IV-5 | two phones use one code at the same moment | a race | the first wins; the second gets IV-4's sentence; **nothing is left half-made** | Built | `join` re-opens the invite inside the transaction and deletes the music-server account on any failure | `test_a_failure_after_the_music_server_made_the_account_leaves_nobody_half_made` |
| IV-6 | the typed code differs in case or dashes | a person reads it aloud | accepted (the code has no 0/O/1/I/L) | Built | `hash_code` | `test_the_code_is_the_same_typed_in_any_case_with_or_without_dashes` |
| IV-7 | the music server cannot make accounts (it was reset, its administrator login changed) | operations | "This server is not set up to add or change people yet." (code `server_busy`; no crash) | Built | `_need_admin` | `test_a_server_that_cannot_make_accounts_says_so_instead_of_failing` |
| IV-8 | the link **names the key** of the server (`?id=<26 characters>`) | the owner's phone makes the link with the key it knows; the new phone asks the address who it is **before anything else** (before the invitation is even looked up, so no name and no password is sent) and only goes on if the key is that one; a link with a malformed key is refused, not read as a link without one | "This is not the server that invited you. Ask for a new invitation." | **Built** (P2-19 slice A) | `invite_link.dart`, `join_screen.dart` `_ask`, `encore_people.dart` `joinLink` | `invite_link_test.dart`, `join_invitation_test.dart` (a key that is not proved sends nothing; a server with no key is refused for a link that names one; an older link with no key still works) |

## 4. The states of a person

```
(invited) -> active <-> locked -> (removed)
               |  ^
         reset link  (devices signed out, lock cleared)
```

| ID | State / event | Caused by | Effect | What the person sees | Status | Where | Test |
|----|---------------|-----------|--------|----------------------|--------|-------|------|
| AC-20 | **active** | joined or signed in | can use everything their role allows | Home | Built | `person` | many |
| AC-21 | wrong password for a name that exists | anybody | counted for the owner to see and **slowed** (five wrong answers a minute for one name from one address, thirty for one address; then 429 with a wait): **a wrong password never locks an account and never signs a device out** (AUDIT B2, D-41: it let a stranger lock the only owner out of his own server); a correct login the music server has already vouched for is never held up; a name nobody has is neither counted nor locked | the sentence "The username or the password was not accepted." | Built | `failed_login` (`LOCK_AFTER_FAILURES = 20`) | `test_twenty_wrong_passwords_lock_the_account_until_the_owner_unlocks_it`, `test_a_name_nobody_has_is_not_counted_or_locked` |
| AC-22 | **locked** | an owner locks them (never a wrong password) | every request is refused **before the password is looked at**, so the answer never says whether a guess was right; devices revoked | "This account is locked. Ask the owner of this server to unlock it." | Built | `update_person` | `test_locking_a_person_signs_their_devices_out_and_unlocking_lets_them_back` |
| AC-23 | **unlocked** | an owner | the failed-count resets; the person signs in again (their devices were revoked) | the card "Sign in again" (`31` CN-24) | Built | `update_person` | same |
| AC-24 | **password reset** | AC-6 | new password; all devices revoked; one new device | signed in on the phone that used the link | Built (server) | `reset_password` | `test_a_reset_link_expires_and_a_new_one_cancels_the_old` |
| AC-25 | **password changed by the person** | the person, in the app | needs the old password; **other devices are signed out** | the other phones show "Sign in again" | Built (server `POST /me/password`) | `change_password` | `test_changing_your_own_password_needs_the_old_one_and_signs_the_other_devices_out` |
| AC-26 | **removed** | an owner | the music-server account, library, history and devices are deleted; **the music files stay** | the person's phone shows "Sign in again", then nothing works | Built | `remove_person` | `test_removing_a_person_removes_their_account_and_everything_they_had` |
| AC-27 | an owner demotes, locks or removes the **last owner**, or locks or removes **themselves** | an owner | refused: "A server needs at least one owner…", "You cannot lock yourself out." | Built | `update_person`, `remove_person` | `test_the_last_owner_cannot_be_demoted_locked_or_removed_and_nobody_locks_themselves` |
| AC-28 | **the Host forgot their own password** | the Host | `encore reset-password <name>` on the server (physical access is the proof) | the terminal | **Designed** (`26` §5); the command does not exist yet | none | none |
| AC-29 | **leaves** (export, delete my account) | the person | their data exported, then removed | a "Your data" screen | Designed (`21` §6, P3-09) | none | none |

Who may do what: an owner makes and revokes invitations, sees the people list (names, roles and counts, **never what anyone plays**: ADR-R33), changes roles, locks, unlocks, removes, makes
reset links. A member may only change their own name and password. (`test_a_member_cannot_make_invitations_or_see_people`, `test_the_owner_sees_names_roles_and_counts_and_nothing_else`.)

## 5. Every way a phone gets onto a server

"Joining" here means a phone ends up signed in on a server. What is needed and what can go wrong, for each way.

| ID | Way | Needs | What happens | If it fails | Status | Where | Test |
|----|-----|-------|--------------|-------------|--------|-------|------|
| JN-1 | **Open an invitation link** (tapped in a message, or a QR scanned with the phone's own camera) | the link; the phone has Encore | the app opens on the join screen: it asks who invited you (retrying 2, 4, 8 s while the network wakes up), then a name and a password, then "Making your account…", "Signing you in…", Home | the sentences of `31` CN-31/32 and IV-4; if the account was made but signing in failed: "Your account … is made, but signing in did not work just now. Tap \"I already have an account\"" | Built | `join_screen.dart` | `join_invitation_test.dart`, `android_invite_links_test.dart` |
| JN-2 | **"I already have an account"** (on the join screen, or the first screen) | the address, a username, a password | the typed form: Subsonic check, then the person signs in as AC-4 | `31` CN-30/31 | Built | `connect_screen.dart` | none |
| JN-3 | **"Got a setup link? Paste it"** | a message the sender wrote | fills in what the sender knew (address, name) so only the password is typed | "No setup link found. Copy the message you were …" | Built | `connect_screen.dart` | none |
| JN-4 | **An invitation for a server this phone already has an account on** | the link | says so, and does not make a second account | — | Built | `invite_link.dart` `isForServer` | `invite_link_test.dart` |
| JN-5 | **Add someone on this device** | a phone that already has a profile | "Who's listening?" > Add someone: sign in (AC-4) or an invitation (AC-2); the new profile is added without touching the others | the same sentences | Built | `features/profiles/profiles_screen.dart` | `profiles_test.dart` |
| JN-6 | **The owner's pairing link or QR** | printed by the installer or `encore pair` | AC-7: signed in, no typing | an expired or used code: the IV-4 sentence | Designed | none | none |
| JN-7 | **"Servers on this Wi-Fi"** | the phone and the server on one home network | the server appears by name; tapping it asks for a login or an invitation (finding grants nothing) | nothing found: the other ways stay | Designed (slice C) | none | none |
| JN-8 | **Quick Connect** | a found server; any signed-in device | AC-8 | the code expires after 5 minutes (proposal) | Designed (slice D) | none | none |
| JN-9 | **A typed address with no account** | an address only | not possible: an address alone joins nothing; the person needs one of the above | "The server is there, but the username or password was not accepted." | Built | `connect_screen.dart` | none |
| JN-10 | **An old install's phone** keeps working after the server is migrated (AC-5) | the same address and login | the person's likes and playlists are there | `31` CN-24 if the login changed | Built (server); the banner "Your music moved" is open | `migration.py` | `test_migration.py` |

## 6. The states of a device

A device row is made at every sign-in that has no usable token (`issue_device`): AC-2, AC-4's `POST /auth/login`, AC-6. The token is shown **once**; only its hash is stored.

| ID | State / event | Caused by | Effect | What the person sees | Status | Where | Test |
|----|---------------|-----------|--------|----------------------|--------|-------|------|
| DV-1 | **issued → active** | a sign-in | each request marks `last_seen` (at most once a minute) | the owner's people list shows when somebody last signed in, never what they play | Built | `get_principal` | `test_the_owner_sees_names_roles_and_counts_and_nothing_else` |
| DV-2 | **revoked: sign out** | the person signs out | the app asks the server to end this phone's device (`POST /auth/logout`, the music server's login plus `X-Encore-Device` naming the device; best effort, five seconds at most) and deletes the saved device sign-in `encore.device.<n>` whatever the answer; then the phone deletes the server's data from itself (`31` CN-28). **Only the caller's own device can be ended this way** (the server checks the device belongs to the person: the header comes with the music server's login, not with the device token). Offline: the device stays valid on the server until the person ends it from another device (DV-3) | the phone shows the first screen | **Built** (D-5, walked on a phone: `evidence/b05`) | `api.py` `logout`; `sign_out.dart`, `EncoreDevice.signOut`, `ServerSession.endDevice` | server `test_dv_2_the_app_signs_its_device_out_with_its_normal_login_and_its_device_header`, `test_dv_2_signing_out_never_ends_somebody_elses_device`; app `DV-2: signing out ends the device of this phone on the server and deletes the saved sign-in`, `DV-2: signing out with no connection still forgets the sign-in, and says the server was not told`, `DV-2: a phone that never signed in as a device has nothing to end`, `DV-2: ending the device of a session tells the server which phone it was and forgets the saved sign-in` |
| DV-3 | **revoked: one device** | the person, from another device (`DELETE /me/devices/{id}`) | that device is signed out (its next request is refused) | "Sign in again" on that phone | Built (server); **no list of devices and no "sign out that phone" screen in the app** | `api.py` `revoke_device` | none |
| DV-4 | **revoked: lock, reset, password change, removal** | AC-21 to AC-26 | all of the person's devices (or all the others) | `31` CN-24 | Built | `accounts.py` | see §4 |
| DV-5 | **lost or stolen phone** | the person | revoke it from another device or an owner removes it; **its downloads stay but stop playing after the token is revoked (the app checks at start)** | as DV-3 | Designed (`26` §4); needs the device list screen | none | none |
| DV-6 | **unused for 180 days** | time | the device disappears from the list | nothing | Designed (`26` §4) | none | none |
| DV-7 | **a new phone for a known person** | a sign-in | a new device row; settings are not carried over yet | "Download the same playlists as on <old phone>?" | Designed (`26` §4, P3-10) | none | none |
| DV-8 | **two profiles on one device** | AC-9 | each profile has its own token, library and downloads; picking one needs no password; sign-out with others present returns to the picker | the picker | Built (first slice) | `profiles/` | `device_profiles_test.dart` |

## 7. Limits that protect the account (one place)

| What | Limit | Where | Test |
|------|-------|-------|------|
| sign-in attempts | 5 a minute per name, 20 a minute per address; then a wait that says how long | `Limiter`, `api.py` `login` | `test_five_tries_a_minute_for_one_name_and_then_a_wait_that_says_how_long` |
| joining, checking and resetting by link | 10 to 20 a minute per address | `api.py` | `test_joining_is_rate_limited_per_address` |
| wrong answers before a wait | 5 a minute for one name from one address, 30 for one address | `LoginGuard.PAIR`, `LoginGuard.ADDRESS` | `test_public_edge.py` |
| an invitation | 7 days, once | `INVITE_TTL_S` | `test_an_expired_or_revoked_invitation_does_not_work` |
| a reset link | 1 hour, one live link per person (a new one cancels the old) | `RESET_TTL_S` | `test_a_reset_link_expires_and_a_new_one_cancels_the_old` |
| a pairing code (designed) | single use, 10 minutes, never logged | ADR-R40 D7 | none |

## 8. Debts this document makes visible

* **D-1:** AC-6 and DV-3 are built on the server and **have no screen**: a person who forgot their password cannot use the owner's link in the app, and nobody can see or sign out their own other phones. P2-18 follow-up / P3-10.
* **D-2:** JN-2, JN-3, JN-9, DV-2 have no test.
* **D-3:** the first screen still leads with the typed form (`31` CN-20); JN-6 to JN-8 are the answer.
* **D-4:** the phone keeps the person's password (`31` D-1).
* **D-5 (done 2026-10-24, `evidence/b05`):** ~~signing out on the phone does not revoke its device on the server~~ it does now; the same work closed a hole on the server (`/auth/logout` ended whatever device id came in the header, not only the caller's own). The text below is the finding as it was written: **signing out on the phone does not revoke its device on the server** (no call to `POST /auth/logout`, and the saved device token `encore.device.<n>` is not deleted): the device stays in the person's list and its token stays valid. Fix: sign-out revokes first (best effort, offline is fine), then deletes the token with the rest.

## 9. Open

| ID | Question | Who |
|----|----------|-----|
| O-1 | Can a **member** make an invitation for a friend (a "guest")? Today only owners can. (Proposal: no; the owner is the gate, as the owner said on 2026-10-17.) | product |
| O-2 | What does an **expired Quick Connect or pairing code** say, and may the owner see which devices used which? (Proposal: the IV-4 sentence; the owner sees the device's name and date only, ADR-R33.) | **Decided 2026-10-23: as proposed** |
| O-3 | A person is removed while their phone is mid-song: the song finishes, then "Sign in again"? (Proposal: the next request fails; the player keeps what is buffered.) See `33`. | **Decided 2026-10-23: as proposed** |
| O-4 | Does a **removed** person's phone keep its downloads? (Proposal: yes until signed out, but they stop playing after the token check at app start, as `26` §4 designs.) | product |
| O-5 | Do a person's **two accounts on two servers** share anything on one phone? (Proposal: no; two profiles, two libraries.) | product |
