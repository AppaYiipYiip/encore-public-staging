# 21 — Security, privacy and roles

> **In short.** Who may do what and see what: the roles, the privacy matrix, which route is reachable from the home network and from the public address, how credentials and one-time codes work, family settings, leaving, and the threat model. The matrix is enforced on the server. Known gaps are marked in place: the explicit-songs switch is stored and not enforced (B-6), revoking a device does not stop the shipped app (B-55), the password-encryption key is planned (B-27, P3-30).

Why: a server in people's homes, reachable from the internet, holding a household's listening, talking to other servers. The old
project handled pieces (a proxy-header guard, people roles) but never wrote down who may do what, who may see what, or what an attacker
could try. Binding for P2–P4.

## 1. Roles

| Role | Who | Has |
|------|-----|-----|
| **Owner** | The Host (one or more owners per server) | Everything in the admin; manages people; never sees members' libraries or listening |
| **Member** | Family, friends with an account | Their own library, devices, friends, Jams |
| **Jam guest seat** (D-15) | Someone with no Encore server, for one Jam | Join that Jam, see its queue, add songs from search; no library; gone when the Jam ends |
| **Remote friend** | A person on another Encore server (federation) | What the friendship and the person's sharing settings allow (`13` §4) |
| **Device** | A signed-in phone/tablet/PC | Acts for one person; revocable one by one |

## 2. Who can see what (privacy matrix)

| Data | The person | Owner (Host) | Other members | Remote friends | Jam participants |
|------|-----------|--------------|---------------|----------------|------------------|
| Their library, playlists, likes | ✓ | ✗ | ✗ (unless shared/collaborative) | ✗ (unless sent) | ✗ |
| History, Year in Music, recommendation profile | ✓ | ✗ | ✗ | ✗ | ✗ |
| What they play now | ✓ | ✗ | only if they share activity | only if they share activity | the Jam's queue only |
| Their devices | ✓ | names and last seen | ✗ | ✗ | ✗ |
| Storage they caused | ✓ | **counts and sizes only** | ✗ | ✗ | ✗ |
| Problem reports | ✓ (sent with consent) | ✓ | ✗ | ✗ | ✗ |
The server's logs never contain song titles tied to a person (only ids), passwords, tokens or signed URLs.

## 3. Where each part is reachable

| Route | Home network | Public address (Funnel) |
|-------|--------------|-------------------------|
| App API, live channel, streams | ✓ | ✓ |
| Invite/join, Jam join | ✓ | ✓ |
| Server-to-server (`/encore/federation/…`) | — | ✓ (only if D-13 allows) |
| Setup wizard | ✓ with the setup code (`15` §1) | ✗ |
| Admin site | ✓ | ✗ (reach it remotely only through the Host's own Tailscale, Advanced) |
| Navidrome's own web UI (through the gateway) | ✓ | ✗ (since S1, B12 `gateway.py`) |
| Navidrome's Subsonic API under `/rest/` (through the gateway) | ✓ | ✓ for members' Subsonic apps **with a token login** (`u`, `t`, `s`); wrong sign-ins are slowed like every other door and a locked account is refused first (B12b, `api.py` `authorize_public_subsonic`). **Known limit:** an app that can only send a plain password (`p=`, `p=enc:`) or an API key cannot sign in through the public address; at home nothing changed. *(Until B12b this row said "rate-limited" and it was not: 40 wrong sign-ins in 0.6 s were all answered, measured 2026-11-03 on the dev server.)* |

## 4. Credentials

* Passwords live only in Navidrome (which needs them reversible for the Subsonic protocol), stored under **this install's own key**, `ENCORE_PASSWORD_KEY` in `.env` (48 random letters and digits made by the installer before the first start, handed to the music server as `ND_PASSWORDENCRYPTIONKEY`; without one Navidrome uses a key that is the same in every install and is in its public code, B-27). **The key is never changed and never lost:** a different key, or none, makes every sign-in fail until the right one is back (measured on Navidrome 0.64.2; setting a key on an install that never had one keeps every login working, it locks them again). A fingerprint of it is kept beside the music server's data (`navidrome/.encore-password-key.sha256`), and a missing or different key is **refused in words, never replaced** by the installer, `encore update` or `encore secure`. It is in every backup. Phones never store passwords after sign-in: they hold a **device token** (256-bit random, stored hashed),
  revocable per device (**planned, not built:** expiry after 180 days unused, `32` DV-6).
* **A backup is secret material**: it holds the accounts, the server's private identity key, the key that signs song addresses, the music server's administrator login and its password key (so a stolen copy could impersonate the server and open every password). Every backup is therefore **locked to a public key** (age, X25519) kept in `/opt/encore/backup.pub`; the secret half is shown to the Host once, by the installer or `encore secure`, and is kept **nowhere on the computer** (so the nightly backup needs nobody to type anything, a copy taken away cannot be opened by whoever finds it, and a thief of the computer cannot open the old copies). Restoring needs that key (`encore restore FILE`, asked for or read from a file; never part of a command). Without it a backup cannot be opened by anybody; `encore secure --check` says whether the key a Host saved is the right one. Backups made before this stay plain files and still restore, with a sentence saying they are not locked. Navidrome's own nightly copy of its database (`navidrome/backup/`) holds passwords locked with the install's key, so it is no more exposed than `navidrome.db` itself.
* One-time codes: setup code (until the owner exists), pairing QR (10 min), invite (7 days, one person), friend code (24 h), Jam code
  (until the Jam ends), password-reset link (1 h).
* Rate limits: wrong passwords are slowed, never punished with a lock: 5 wrong answers a minute for one name from one address and 30 for one
  address, then a wait that says how long (`LoginGuard`; `32` AC-21 and §7). **A wrong password never locks an account and never signs a device out**;
  only an owner locks an account (S1, AUDIT B2). Navidrome's own limiter sees real client addresses (the existing secret-header rule, ADR's D-2).
* At home, traffic may be plain HTTP on the Wi-Fi: acceptable only because no password crosses it after pairing; HTTPS at home with a
  certificate pinned by the pairing QR is planned (H30, P5).

## 5. Family and kids

* Per person: "Explicit songs" on/off (from the catalogue's flag); the owner can set and lock it for a member. **Not enforced yet (audit B-6, 6 Nov 2026):** the value is stored and settable, but no server code and no screen filters by it; enforcement is part of the server-search task (P2-12), and the admin People page must not draw the switch until it works.
* A device can be **shared** (a living-room tablet): other members of the server may play on it (like a Connect speaker), each with
  their own queue; the device's owner can turn it off (P4-07).

## 6. Leaving

* **Export:** a member can download their library (playlists, likes, history) as JSON and CSV (Settings → Your data).
* **Delete my account:** removes library, history, profile, devices, friendships, shares; songs kept on the server stay if anyone else
  saved them, otherwise they become "nobody saved" (removable by the owner). The owner can do the same for a member.
* **Federation:** removing a friend or turning federation off deletes the other server's grants and stops all shares at once.

## 7. Threat model (what an attacker could try, and what stops it)

| Who | Tries | Stopped by |
|-----|-------|-----------|
| Stranger on the internet | guess passwords; reach the admin; exhaust the server | rate limits (a wrong password slows a guesser and never locks an account); admin not public; per-address limits on public routes; only the music server's Subsonic API passes through the public address (S1) |
| Stranger on the home Wi-Fi | claim a fresh server; sniff traffic | setup code (H36); tokens not passwords; pinned HTTPS later |
| Curious member | see others' listening; read others' playlists | the privacy matrix enforced server-side, tested (one test per cell of §2) |
| Malicious remote server | spam friend requests; pull a library; stream everything | codes from a person, signed requests, pinned keys, grants scoped to one song in one live Jam, per-server rate limits, Host switch |
| Lost or stolen phone | play as the person; read their library | revoke the device from another device or the admin; tokens hashed on the server. **Not true for the app of build 125 until P3-03 and P2-20** (audit B-55: its calls carry the music-server login, which a revoked device keeps); until then a locked account or a changed password is what cuts a phone off |
| Forwarded invite link | a stranger joins | one-time use, 7-day expiry, owner sees who used which invite and can remove them |
| Compromised dependency | malicious update | pinned versions, checksums on releases, `pip-audit`/`osv-scanner` and Dependabot in CI, yt-dlp updates pinned to releases ≥ 24 h old and verified by hash |

## 8. Tests

One automated test per cell of the privacy matrix and per row of the threat model where automatable; a security review by a fresh
agent before P5 (`06` §4) using this page as its checklist.
