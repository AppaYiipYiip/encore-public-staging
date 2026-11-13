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
| Deezer (`api.deezer.com`), the server's **cover finder** | the server | the first artist and the title of songs that have no picture yet, up to 300 per pass, once per album, retried after a week. This includes songs from the Host's own collection | in the background, after the library changes | not yet (planned) |
| PyPI (`pypi.org`) | the server | a request for the newest `yt-dlp`, once a day (nothing about people) | in the background | yes: `ENCORE_AUTO_TOOLS=0` |

## What leaves the phone

Today the **app itself** calls two public catalogues directly, so each sees the phone's internet address and the words involved:

* **Deezer** (`api.deezer.com`): the words typed in search, to show artist and album results and pictures.
* **LRCLIB** (`lrclib.net`): the song title, artist, album and length, to fetch lyrics.

Moving both to the server (so the phone only ever talks to your own server) is planned and tracked in the roadmap.

## Programs that run beside Encore

The stack runs **Navidrome** as the music library. Encore's `compose.yaml` turns Navidrome's usage statistics off (`ND_ENABLEINSIGHTSCOLLECTOR=false`) and sets nothing else about its outside calls. By Navidrome's own defaults it also looks up artist information and pictures at **Deezer** and **ListenBrainz** (artist names are sent; Last.fm only if the Host adds a Last.fm key), and its login screen fetches a background picture from **Unsplash**. The Host can switch all of this off with `ND_ENABLEEXTERNALSERVICES=false` (see Navidrome's documentation); Encore does not set it today.

Add-ons a Host chooses to run beside Encore (for example the Soulseek and Lidarr add-ons) contact their own networks; they are not part of the default stack.

## Friends on other Encore servers

If you turn on "Friends on other Encore servers": only what each feature needs, and only after both people agree (see `docs/13-devices-jam-and-friends-across-servers.md`).

## The Host

Encore is designed so that the Host has no screen showing what members listen to or what is in their libraries
(`docs/21-security-privacy-and-roles.md`). The Host does run the machine, so they can technically reach its data: join a server whose
Host you trust. If the Host uses Tailscale Funnel for a public address, that traffic also passes through Tailscale's network; see Tailscale's own policy.
