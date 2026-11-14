# Privacy

Encore has no central service run by this project. Your music, playlists, likes and listening history are stored on **your own server**
(the "Host" is whoever runs it). The app is built to talk to your own server; two small features are still asked from the phone directly
(see below), and that is listed here instead of hidden.

The tables below are written from Encore's own server and app code (`git grep` for the hosts finds every place); if a change adds an outside host, this page must name it. Programs that run beside Encore behave on their own and are listed in the section after the tables.

## What leaves your server

Only when the matching feature is in use. Nothing here carries an account, a name or a listening history.

| Outside service | Called by | What is sent | When | Can the Host switch it off? |
|-----------------|-----------|--------------|------|-----------------------------|
| YouTube and YouTube Music (`music.youtube.com`, `www.youtube.com` and Google's video hosts) | the server | the song title and artist name, to find a song you do not have; then the audio is fetched from **the Host's internet address** (YouTube sees the Host's address, never a member's) | when someone plays or saves a song the server does not have | yes: `ENCORE_YOUTUBE=0` (default: on) |
| Spotify (`open.spotify.com`) and YouTube playlists | the server | the public playlist link you paste, to read its public page | only when someone imports a playlist | not needed unless used |
| Deezer (`api.deezer.com`), the server's **cover finder** | the server | the first artist and the title of songs that have no picture yet, up to 300 per pass, once per album, retried after a week. This includes songs from the Host's own collection | in the background, after the library changes | yes: `ENCORE_CATALOGUE=0` (default: on) |
| Deezer (`api.deezer.com`), the server's **artist-picture finder** | the server | one artist name and the title of one of its songs, for an artist the music server has no picture for and whose songs this server itself saved (never songs of the Host's own collection): at most 20 artists and 3 songs each per pass, retried after a week | in the background, once an hour | yes: `ENCORE_CATALOGUE=0`, the same one switch (audit B-88; its page in the Host's settings is task P3-09) |
| Deezer (`api.deezer.com`), the server's **catalogue pages** (search, an artist, an album, a genre; built in P2-12 slice 1, **the app does not use them yet**: until it does, the phone asks Deezer itself, see below) | the server | the words a person typed in search, or the number of the artist, album or genre they opened, asked **from the Host's internet address** (never the phone's), nothing that names the person; at most 30 outside requests a minute for one person; every answer is remembered on the server, in a file of its own (`catalogue-cache.db`, never backed up, safe to delete), under a hash: the words typed are not kept and not written in the log | only when an app asks | yes: `ENCORE_CATALOGUE=0` (default: on); the server then opens no connection to Deezer at all and does not list the feature |

Every request this server makes to Deezer, whichever of the three above asks, goes through **one gate**: at most 20 requests in 5 seconds in all (Deezer's own published limit is about 50), at most 4 at once, a person's request before background work, and a rest of 30 seconds (doubling up to 10 minutes) after Deezer refuses or throttles a request, during which the server asks nothing and says so in words. A catalogue that could not be asked is never taken for "there is nothing".
| PyPI (`pypi.org`) | the server | a request for the newest `yt-dlp`, once a day (nothing about people) | in the background | yes: `ENCORE_AUTO_TOOLS=0` |

## What leaves the phone

Today the **app itself** calls two public catalogues directly, so each sees the phone's internet address and the words involved:

* **Deezer** (`api.deezer.com`): the words typed in search, to show artist and album results and pictures.
* **LRCLIB** (`lrclib.net`): the song title, artist, album and length, to fetch lyrics.

* **Pictures.** The pictures in those results (and in the server's own answers, which carry the address of a picture, not the picture) are loaded by the phone from **Deezer's picture host** (`cdn-images.dzcdn.net`), so it sees the phone's address. The thumbnail of a song that came from a YouTube playlist is loaded from **YouTube's picture host** (`i.ytimg.com`).

Moving the two calls to the server (so the phone only ever talks to your own server) is planned and tracked in the roadmap: the server side of the Deezer part is built (the row above), the app does not use it yet, and the pictures stay with the picture hosts until a later item serves them through your server.

## Programs that run beside Encore

The stack runs **Navidrome** as the music library. Encore's `compose.yaml` turns Navidrome's usage statistics off (`ND_ENABLEINSIGHTSCOLLECTOR=false`) and sets nothing else about its outside calls. By Navidrome's own defaults it also looks up artist information and pictures at **Deezer** and **ListenBrainz** (artist names are sent; Last.fm only if the Host adds a Last.fm key), and its login screen fetches a background picture from **Unsplash**. The Host can switch all of this off with `ND_ENABLEEXTERNALSERVICES=false` (see Navidrome's documentation); Encore does not set it today.

Add-ons a Host chooses to run beside Encore (for example the Soulseek and Lidarr add-ons) contact their own networks; they are not part of the default stack.

## Friends on other Encore servers

If you turn on "Friends on other Encore servers": only what each feature needs, and only after both people agree (see `docs/13-devices-jam-and-friends-across-servers.md`).

## The Host

Encore is designed so that the Host has no screen showing what members listen to or what is in their libraries
(`docs/21-security-privacy-and-roles.md`). The Host does run the machine, so they can technically reach its data: join a server whose
Host you trust. If the Host uses Tailscale Funnel for a public address, that traffic also passes through Tailscale's network; see Tailscale's own policy.
