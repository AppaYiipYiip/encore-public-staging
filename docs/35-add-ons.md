# 35 — Add-ons: one model for everything optional (P3-20)

> **In short.** Every optional thing Encore can do (songs from YouTube, the catalogue's pictures, the album pass, the higher-quality source, an existing music server, the away-from-home address, where backups go, friends on other servers, updating by itself at night) is an **add-on** with **one of three states**: *Encore runs it*, *Yours* (the person already runs one: an address and a key, health-checked) or *Off*. Each add-on is written ONCE, as a **manifest** in the server; the setup pages, the admin pages, the `encore` command, the words the app reads in `GET info` and the table below all come from that one list. It is the design that P3-20 asks for, written before the setup pages are changed or built (D-61); which add-ons exist in the code is the column "Built", how far each slice is is on the board.

Start from, and do not redo: wizard pages 5 and 7 and the admin Settings page (`15` §2, §4; drawings W-01, W-07), D-12/D-19 (the higher-quality source is an explicit choice, off by default, with a plain-words legal note), D-13 (friends on other servers: on by default, each connection needs two yeses), D-20 (no YouTube account), ADR-077 (optional things are off with safe defaults), ADR-R25 (never replace what is already on the machine), P3-11 (the Tinkerer's door), P4-04 (the lossless stack), P3-13 (storage).

## 1. The three states, and the words that go with them

| State | Means | The person sees | The server keeps |
|-------|-------|-----------------|------------------|
| **Encore runs it** | The add-on is part of the installation (inside the Encore server, or a container the installer added). | "On" and what it is doing now ("last checked 3 minutes ago"). | Nothing the person must look after. |
| **Yours** | The person already runs one (a music server, a reverse proxy, a place for backups). Encore uses it and never installs a second. | The address, the account's name, and a plain health line ("answering" / "does not answer: the password may have changed"). | The address and the key in the add-on's own settings; the key is never shown again and never logged. |
| **Off** | Not used. Switching off hides the feature and stops its work. | "Off", and what the person gets back by turning it on. | **Nothing already made is deleted**: songs kept, pictures found and stamped albums stay. The text says so where it matters. |

Rules that hold for every add-on:

1. **A plain risk text before "on"**, shown at the moment of choosing, in the wizard and in the admin alike, and again whenever its version changes (`risk_text_version`). A risk is something a stranger could be hurt by (the law, a permanent change of their files, an address made public), not a technical detail.
2. **Off is safe and everything works with it off**: the app follows capabilities (`GET info` `features`), so a feature whose add-on is off is not drawn, not greyed with an error. The one exception is the *planned* add-on (not built yet): the admin shows a grey "later" line, neither hidden nor faked (D-19).
3. **"Yours" never changes what it points to** beyond what its text says ("Encore adds songs it keeps to one folder it owns; everything else stays read-only", ADR-R25). Removing Encore (`encore uninstall`) leaves it exactly as it was.
4. **Two doors, one operation** (D-61): every change of state is a button AND a command (`encore addon <id> on|off|yours --address ...`), and both call the same function (`36` §1).
5. **A change that needs a restart says so, and offers the button** ("Restart Encore to apply: it takes about 10 seconds"); a change that can apply live does, and says "applied".

## 2. The add-ons, with their defaults

"Built" says whether the add-on exists in the server; "Switch" is how the Host changes it. Every environment variable named is read once at start (`config.py`): without §4 the Host can change none of them except by editing `.env` and restarting.

| Add-on (id) | Gives | States allowed | Default | Built, and the switch |
|-------------|-------|----------------|---------|-------|
| Songs you don't have (`youtube`) | Play and keep songs from YouTube (D-20: no account) | runs / off | **runs** | `ENCORE_YOUTUBE`; built; the status and the rest are on `GET info` |
| Pictures, search and artist pages (`catalogue`) | The catalogue (Deezer's public search) through this server | runs / off | **runs** | `ENCORE_CATALOGUE`; built; off opens no connection at all |
| Real albums (`album-pass`) | Stamps a song's album from the catalogue | runs / off | **runs** | `ENCORE_ALBUM_PASS`; built (N-34). Risk text: a stamp is permanent and reaches the Host's disk through a later keep |
| Music server (`music-server`) | Scanning, accounts, streaming of the Host's own files (Navidrome) | runs / **yours** | **runs** | built as *runs*; *yours* is P3-11 (the Tinkerer's door) |
| Higher-quality songs (`lossless`) | Soulseek through slskd + Soularr (D-12/D-19, P4-04) | runs / yours / off | **off** | not built: a grey "later" line. Risk text with the legal note (`09` §5) |
| Away from home (`away`) | An address that works outside the house (Tailscale Funnel, ADR-R25) | runs (the computer's own Tailscale) / yours (an address the Host already has) / off | **off** until set up | `encore funnel on`; the admin page and the wizard page 6 are drawn, not built |
| Where backups go (`backups`) | A copy of the databases, nightly | runs (a folder on this computer) / yours (another place: a mounted path now; others later) / off | **runs** (nightly, seven kept) | `encore backup`, `autobackup`; the place is fixed |
| Friends on other servers (`federation`) | Jam and sharing with people who run their own Encore (D-13) | runs / off | **runs** (needs `away` to work: says so) | not built (P4-09) |
| Update by itself at night (`auto-update`) | Takes new versions without being asked, with the way back (P3-14) | runs / off | **off** (a visible choice at install, B-43) | not built |
| Lyrics (`lyrics`) | Words that follow the song, asked of one outside source once for everybody (P2-14) | runs / off | **runs** | draft PR #1, held until the release candidate |
| Suggestions (`recommendations`) | "Made for you" shelves (P4-05) | runs / off | **runs** | not built |

Two things that look like add-ons and are **not**: the owner's own account and the music folder (the wizard asks them; they are the installation), and per-person switches (a person turns off their own notifications or their own sharing: those are the person's settings in the app, `32`).

## 3. The manifest: what an agent who adds the next add-on must write

One file per add-on, `server/encore_server/encore_server/addons/<id>.py`, that builds an `AddOn` value. The wizard, the admin pages, the `encore addon` command, `GET info` and the docs check all read the same list, so a field that is missing fails a test instead of a page.

| Field | Meaning |
|-------|---------|
| `id`, `title`, `summary` | The id (kebab-case, never reused), and two plain sentences. No "Docker", "port", "container", "Funnel" in them. |
| `states` and `default` | Which of runs / yours / off the add-on allows, and the default when nothing was chosen. |
| `needs` | Other add-ons that must be on (`federation` needs `away`). A switch whose need is off says what to turn on first. |
| `risk_text` and `risk_text_version` | The sentence shown before "on" (rule 1). Changing the text raises the version, and the Host is asked again. |
| `settings` | The typed settings it owns: `key`, `type` (bool, choice, integer with a range, text, secret), `default`, the environment variable that seeds it, `live` (applies without a restart) and `secret` (never shown, never logged, never in a backup unless the backup is encrypted, P3-30). |
| `health()` | What `Home` shows: `ok`, `warn` or `fail`, a sentence a person understands, and what to do about it. Called at most once a minute, never makes an outside request unless the add-on's own purpose does. |
| `feature` | The word the app reads in `GET info` `features` when the add-on is on (the app does without a feature it does not find: `17` "Versions"). |
| `profile` | For *runs it* by a container (`lossless`): the compose profile the helper switches on (`36` §3). Empty for an add-on inside the Encore server. |
| `wizard_page` | Where the first-run pages show it (`none` for most: they are in the admin only). |

An add-on that cannot be written in these fields is a sign the model is wrong, and the way to find out is to change this document first (`30`: a change to a page is first a change on paper).

## 4. Where the choices live

* **A new table, `host_setting`**, typed and allow-listed by the manifest: `key`, `value`, `updated_at`, `updated_by`. It is NOT the existing `setting` table: that one is the server's own internal state and holds its **identity private key and the song-signing secret** (`identity.py`, `auth.py`); a settings screen reading it would be a leak waiting to happen. Rule: no route ever reads or writes `setting`; the only door to the Host's choices is the manifest.
* **Order of truth:** the Host's stored choice, else the environment variable, else the manifest's default. `.env` stays what it is today: the install's secrets and its bootstrap (the music folder, the port, the music server's address), not choices. A Host who edits `.env` by hand still gets what they wrote **until** they use the page for that setting once; the page then says "this was set in `.env`; saving here overrides it", because silently overriding a file somebody edited would be a trap.
* **Secrets** (an address's key, a music server's account) are written once, shown as "set" with the day they were set, replaced but never read back, and left out of `GET`, logs and notifications. In a backup they are only inside an encrypted archive (P3-30).
* **The permanent-data rule:** a setting that makes a permanent change on the Host's disk (`album-pass`) says so in its risk text and is off-able at any time; turning it off stops new stamps and removes none.

## 5. The pages and states P3-22 must change (the drawn pages that these rules touch)

1. **W-01 page 5** ("Songs you don't have"): add the "Where songs come from" step of D-19 and D-20's sentence; the higher-quality source as an off-by-default line with its risk text (grey "later" until it exists).
2. **W-01 page 6** ("Away from home"): the page runs the steps itself (`36` §3, closes the OPEN line of `15`); gains the *Yours* state (an address the Host already has).
3. **W-01 page 3** ("Your music"): gains "I already run a music server" (*Yours* for `music-server`) beside the folders.
4. **W-07 Settings** and **W-04 Backups**: become the one add-ons list with the three states (a card per add-on: title, state, health line, the switch, the risk text link). The Storage card of P3-13 sits beside it.
5. **New frame** (not drawn yet): the add-on card's *Yours* form (address, account, "Check"), its failure sentences, and the risk-text sheet.

## 6. Who must point here

P3-11, P3-13, P4-04 and N-05 (each says "its states are the ones of `35`"), `15` (every optional thing: "see `35`"), `10` D-12/D-19 (the manifest is how D-19's step is built), and `17` (the admin routes of `36` §4).
