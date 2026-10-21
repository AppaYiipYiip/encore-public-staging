# 20 — Recommendations: a profile per person (design for P4-01)

Owner: "each one has his own … recommendation system profile tailored to him". Constraints: runs on a Raspberry Pi class machine, no
machine-learning service, no listening data leaves the server, works for a person with 5 plays and for one with 50,000, and every
suggestion is playable (owned or from YouTube).

## 1. What the profile is made of (all per person, from `play_event`, `library_item`, feedback)

| Signal | Weight | Notes |
|--------|--------|-------|
| Played ≥ 70 % of a song | +1 | the main signal |
| Played < 30 s then skipped | −1 | only when the person chose the song or it came from a suggestion |
| Liked / saved album / followed artist | +3 / +2 / +4 | |
| Added to a playlist | +2 | |
| "Not for me" (song / artist) | −10 / hide artist | never shown again unless undone |
| Imported playlists and the first-run artist picks (A5) | +2 per artist | cold start |
Two time scales: **recent taste** (half-life 30 days) and **long-term taste** (half-life 1 year). The profile = artist affinities,
tag/genre affinities (Deezer genres, MusicBrainz tags), and how adventurous the person is (share of plays on new artists).

## 2. Where candidates come from (cheap, public, cached)

1. **Related artists** of the person's top artists: Deezer `/artist/{id}/related` (no key), ListenBrainz similar-artists data
   (public); cached 30 days on the server, shared by everyone.
2. **Top songs** of those artists (Deezer `/artist/{id}/top`).
3. **New releases** of followed and top artists (Deezer `/artist/{id}/albums`, newest first), checked daily.
4. **The person's own past** ("Rediscover": loved long ago, not played for 3+ months; "Deeper cuts": album tracks they never played
   from albums they love).
5. **Country charts** (Deezer `/chart` for the server's country) only for cold start.
Never "what other people on this server play": it would leak friends' listening (`21`).

## 3. Ranking and the rows

`score = affinity(artist or tags) × freshness × (novelty fit to the person) − recently-played penalty − skip history`, then diversity
(≤ 2 songs per artist per row, no song in two rows), then **playability** (owned/kept first; catalogue songs must resolve).

| Row | Content | Refresh |
|-----|---------|---------|
| Made for you (2–6 mixes) | clusters of the person's taste (artists that are often played together), 30 songs each, ~40 % new to them | nightly |
| Because you play *X* | for the top 3 recent artists, related artists' best songs | nightly |
| New from artists you love | releases from the last 4 weeks, unseen first; a notification once per release | daily |
| Rediscover / Deeper cuts | from the person's own past | weekly |
| Radio (from any song/artist) | seed's artist + related artists' top songs + matching songs from the library | on demand, ≤ 2 s |
| Smart shuffle | while shuffling a playlist, about 1 in 5 songs is a suggestion, marked, one tap to keep or skip | live |
Every item carries its reason ("Because you play Opeth").

## 4. Cost and schedule

Nightly per person + incrementally after 20 new plays; CPU ≤ 2 s per person on a Pi 4 for a 10,000-play history (measure in P4-01);
external calls only for artists not in the cache (≤ 100 per person per night); the app caches rows for offline.

## 5. Privacy

The profile is the person's alone; the Host sees only on/off and counts; friends see nothing unless the person shares activity.
Honest limit: asking Deezer for an artist's related artists tells Deezer that *someone at this server's address* is interested in
that artist (not who); caching shared by the whole server blurs it further. Written in the privacy text.

## 6. How we know it is good

* Offline: on real histories (the owner's and test people's), recommend from history up to day *d* and measure how many of the songs
  played in the following week were in the rows (hit rate), against a baseline of "related artists only".
* Online: per row, share of shown items played ≥ 30 s and saved.
* The owner's verdict after a week of his own listening (P4 exit criterion).
