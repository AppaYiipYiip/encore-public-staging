# 12 — The app's signing key (plain explanation and the agreed plan)

Agreed with the owner on 2026-10-21 ("that works, makes sense to me"). Decision D-10. The work is task **P5-01**.

## What a signing key is

Every Android app is **signed** with a key: a small secret file plus a password. Think of it as a **wax seal**.

When you install Encore and later install a newer version, Android checks that the new version carries **the same seal**:

* **Same seal** → it updates normally and keeps everything.
* **Different seal** → Android refuses ("App not installed"). The only way out is to **uninstall the old app first**, which wipes the
  phone's downloaded songs, settings and sign-in.

## Why it matters for Encore

Apps from the Play Store have their key looked after by Google. Encore is downloaded from GitHub (and later a website), so **the key
is ours to look after**.

## The situation today (2026-10-21)

Every Encore build so far is signed with a temporary **debug key** that Android's tools created automatically on the owner's laptop
(`C:\Users\you\.android\debug.keystore`, created 2026-10-14). If the laptop breaks or is reset, that key is gone, every future
build would carry a different seal, and everyone would have to uninstall and lose their downloads. A debug key is also not meant
for releases.

## The plan

1. **An agent creates one proper release key, once** (task P5-01): a keystore file and its password, made for Encore only.
2. **It goes into GitHub's private "secrets" settings**, so every release is signed automatically with the same seal by the release
   pipeline. No release is ever signed on a laptop.
3. **The owner keeps one backup copy** of the key file and its password, on a USB stick or in a password manager. That is the only
   thing the owner has to do. It is in case GitHub or the account is ever lost.
4. **Keep it private.** Anyone who has the key could publish a fake Encore update that phones would accept. It is never committed
   to git, never sent in a chat, never put in a document.

## The one-time cost

When builds switch from the laptop's debug key to the real release key, **the owner and his friend reinstall the app once**.
Playlists, likes and everything else in the library live on the server, so only the phone's downloads need to download again.
After that, **updates just work, forever**: install the new version over the old one and everything stays.

## Rules for agents (P5-01)

* Generate the key with `keytool` (RSA 4096, validity 30 years), alias `encore`; store the file and passwords as GitHub Actions
  secrets; hand the owner the backup through a channel he chooses (never a chat transcript, never git).
* The release workflow signs with it; `apksigner verify --print-certs` must show the release certificate on every published APK.
* Announce the one-time reinstall in the release notes of the first build signed with it, with plain steps.
* Keep `applicationId = app.encore.player` unchanged, so the switch costs a reinstall and nothing more.

## Developer verification (found 2026-10-21, `26` H43)

Google now requires that apps installed on certified Android phones come from a **verified developer**, even when they are installed
from a website: since 30 September 2026 in Indonesia, Singapore and Thailand, and **worldwide in 2027**. The verified developer
registers the app's package name (`app.encore.player`) **with this same release key**. Two kinds of account:
* **Limited distribution** — free, no ID, up to **20 devices**: enough for the owner, friends and testers during the beta.
* **Full distribution** — **$25 once and a government ID**: needed before the public release.
Without it, people could only install Encore through Android's "advanced" install flow or a cable. Decision D-17 (the owner, 2026-10-21): distribute on GitHub only, pay nothing, not now; task P5-07 is parked until Google's rule blocks installs.
