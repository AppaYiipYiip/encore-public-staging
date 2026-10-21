# Scripts for the dev VM (`encore-dev`, 192.168.50.133)

Kept because the experiments and the end-to-end proofs of `docs/46`, `docs/47` and `docs/52` were run with them and will be run again. They are **not part of the kit** (the packer leaves `tests/` out) and are written for the dev VM: they read the throw-away logins in `~/encore-creds.txt` and never print a key or a password. Copy one to the VM with `ssh encore-dev 'cat > file' < file` (strip CRs first: `tr -d '\r'`) and run it there.

| Script | What it does |
|--------|--------------|
| `q.sh owner\|guest METHOD PATH [json]` | calls the quality service as the owner or the guest, the way the app would |
| `qs.sh CONTAINER PORT owner\|guest METHOD PATH [json]` | the same for any service (suggestions: `encore-recs 8705`) |
| `e2e_start.sh` | quality, step 1: a quick copy exists and is liked and in a playlist, Soulseek is switched on, the guest asks for better quality |
| `e2e_verify.sh`, `e2e_phone.sh` | quality, steps 2 and 3: what is true after the swap, and what a phone does with the upgrade map |
| `recs_e2e.sh` | suggestions: the guest plays and likes the library's songs, the owner asks for a rebuild |
| `s2_links.sh`, `s2b_ids.sh` | S2 and S1: hard links across containers on one mount, the dot-folder pool, and what the music server does with a replaced file |
| `s3_lidarr.py` | S3: Lidarr by API (root folder, profiles, one artist, one album) |
| `s4_peer.sh`, `slskd_search.py` | S4: a stand-in Soulseek peer sharing a synthetic album, and a search-only look at a network |
| `s9_navidrome_db.py` | S9: what the music server's database holds per person (read from a copy) |
| `s11_public_sources.py`, `s11_deezer.py` | S11: what MusicBrainz, ListenBrainz and Deezer answer |
| `lidarr_probe.py` | Lidarr's naming settings, command shape and lookup objects |

**The private Soulseek network.** Two programs behind one internet address cannot reach each other on the real Soulseek network, and nothing copyrighted may be fetched to test with. So the dev VM runs **Soulfind** (a 14 MB test server, `ghcr.io/soulfind-dev/soulfind`) and a second slskd (`encore-peer`) that shares a made-up album (silence, named and timed after a real album's track list). The kit's slskd is pointed at it by a test-only `compose.override.yaml` next to `compose.yaml` on the VM (`SLSKD_SLSK_ADDRESS=soulfind`, `SLSKD_SLSK_PORT=2242`) and both are joined to the stack's network (`docker network connect encore-server_default soulfind`). Delete the override to go back to the real network.
