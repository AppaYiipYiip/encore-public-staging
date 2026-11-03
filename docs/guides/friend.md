# Using Encore on a friend's server (a one-page guide for the first outside user)

> **Draft.** Not to be handed over before the gates in `docs/11-decision-log.md` ADR-R34 hold: the owner installed and uses the server, the
> away-from-home address works on mobile data, backups exist. Written now so the words can be tested on the owner first.

Encore is a music app that plays from a server a friend runs, like a private Spotify. You have an account on his server; your playlists, likes
and downloads are yours and separate from his.

## What you need

* An Android phone (Android 7 or newer).
* The app file the server's owner sends you (`Encore.apk`), and the invitation link he sends you.

## Get started (about 3 minutes)

1. **Install the app.** Open the file you were sent. Android asks whether the app you opened it from may install apps: allow it for this
   once. If it warns that the app is from an unknown developer, choose *More details* and *Install anyway*: Encore is not in a store yet.
2. **Tap the invitation link** he sent you (in the chat or e-mail). Encore opens and asks you to choose a username and a password. Use a
   password you do not use anywhere else, and write it down somewhere safe: if you lose it, the owner can only reset it.
3. **Wait a few seconds** while your library arrives. Press play on anything.

If the link opens a web page and not the app, copy it, open Encore, and paste it into *Connect*.

## What to expect

* **It works away from home**, on mobile data too. A song starts in a second or two; a song the server does not have yet takes 5 to 10
  seconds the first time (it is fetched as you press play; playing does not keep it).
* **Downloads** (the arrow on an album or playlist) keep the songs on your phone for the subway and flights.
* **Search** also finds songs the server does not have; pressing play fetches them for you.
* **Lyrics** show when they exist. Many songs have none; that is not a fault of the app.
* **The server is a home computer.** If it is off or being updated, the app says so and your downloads keep playing. Tell the owner if
  it is down for long.
* **Privacy.** The owner can see that you have an account and when you last signed in; Encore does not show him what you play, and he
  agreed not to go looking (his music server has administrator tools that could).
* **The shared shelf.** On the home screen, **New on the server** lists songs that anyone on the server has had kept. It does not say who. You can switch it off in Settings.

## When something is wrong, or you do not like something

Message the owner, in your own words: what you did, what you expected, what happened. A screenshot helps. When he asks for details, open
Encore > *Settings* > *About & credits* > *Diagnostics* and tap the copy icon at the top right, then paste it into the chat. It holds your
phone model, the app version and the last lines of what the app did; it never holds a password, but it does name the server, so read it
over before you send it.

**Small things count.** "This button is hard to hit", "I expected this to be here", "it felt slow at about 6 pm" are exactly what makes
the app better. You do not need to say why.

## Stopping

Settings > *Sign out* removes your login from the phone. To remove your account from the server, ask the owner.
