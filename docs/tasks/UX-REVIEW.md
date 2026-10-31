# UX review of the phone app: every control, and the questions asked of each (AUDIT F44, F37)

Generated from the code on 2026-10-30 by `tools/ux_inventory.py` (the list below), then judged by hand. **It is an inventory, not a walk.** The owner's request: *"test every single feature and question yourself: should this be like this, should it be here, is it not already here, does it make sense?"* The advisor judges it in batches; each verdict becomes a fix, a drawing or a decision, and journey J12 of `RELEASE-CANDIDATE.md` walks the same list.

**Questions asked of every row:** (1) What is it for, and who needs it? (2) Is it already somewhere else (**DUP**)? (3) Is it in the right place? (4) Would somebody who never heard of Navidrome, Tailscale or "refs" understand its words? (5) Does it look like what it is (a hint versus typed text, information versus a button; does it look broken)? (6) Does it work in each mode: Encore or plain server (**MODE**), light or dark, offline, an empty server? (7) Does it follow Spotify's conventions (long-press, the ⋯ menu)? (8) Are its empty and error states in plain words?

**Verdicts (to be filled):** keep, move, merge, remove, reword, fix, needs drawing, P4. **Flags:** `DUP` the same label on more than one screen; `NOOP?` no handler found (a static label, or a control that does nothing: check); `MODE` the code mentions legacy, the request portal, the old fetch service or the old people service: may work on only one kind of server.

**Batches for the advisor:** 1 Home, Library, Search, catalogue album and artist pages, Now playing and its menu, Settings root, Your server. 2 the settings sub-pages, invitations and people, What's new, Jam, Year in Music, profiles, sign-in, join and first run. 3 the states: offline, server away, empty server, the first minutes after sign-in.

**Counts:** 266 controls found in 16 feature folders; 24 labels appear on more than one screen.


## `auth/` (2 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `auth/login_problem.dart:207` | FilledButton |  | onPressed _busy |  | |
| `auth/login_problem.dart:217` | TextButton | Use a different account | onPressed _busy |  | |

## `catalogue/` (13 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `catalogue/adding_music_help.dart:143` | PopupMenuItem | Ask for better quality | - | NOOP? | |
| `catalogue/adding_music_help.dart:145` | ListTile | Ask for better quality | - | NOOP? | |
| `catalogue/adding_music_help.dart:152` | PopupMenuItem | How does this work? | - | NOOP? DUP | |
| `catalogue/adding_music_help.dart:154` | ListTile | How does this work? | - | NOOP? DUP | |
| `catalogue/catalogue_screens.dart:51` | Chip | In your library | - | NOOP? DUP | |
| `catalogue/catalogue_screens.dart:57` | Chip | Adding $ready of ${tracks.length} | - | NOOP? | |
| `catalogue/catalogue_screens.dart:65` | OutlinedButton.icon | Add to library | onPressed tracks.isEmpty |  | |
| `catalogue/catalogue_screens.dart:79` | Chip | In your library | - | NOOP? DUP | |
| `catalogue/catalogue_screens.dart:85` | Chip | Adding to your library | - | NOOP? | |
| `catalogue/catalogue_screens.dart:93` | OutlinedButton.icon | Add to library | onPressed tracks.isEmpty |  | |
| `catalogue/catalogue_screens.dart:146` | IconButton | Download ${album.title} for offline listening | onPressed tracks.isEmpty |  | |
| `catalogue/catalogue_screens.dart:227` | InkWell | How does this work? | onTap () => | DUP | |
| `catalogue/genre_screen.dart:85` | ListTile | Artist | onTap () => |  | |


## Mechanical findings (leads to judge, not verdicts; from the duplicate and flag scan, 2026-10-30)

* **M1. Three import screens.** `import/import_screen.dart`, `import/encore_import_screen.dart` and `settings/import_screen.dart` (Settings > Import music) share "Choose a file" and "Paste from clipboard". Which one is the import on an Encore server (the server reads the list), and which are the old portal's? A person must meet one.
* **M2. Two invitation flows.** `people/people_screen.dart` with `people/invite_dialog.dart`, and `settings/invite_someone.dart`: both say "Invite someone" and "Copy link". One flow, one place (and F39: its words). **Reasoned from the code, 2026-10-30 (advisor):** on an Encore server `peopleApiProvider` chooses `EncorePeopleApi` (Encore's own invitations; the link is `/encore/join/<code>?id=<server key>`), so on the release-candidate pair only the service invitation shows, and the setup-link dialog appears only on a plain music server. So M2 is **later**, not RC1, provided the session's mode is right. Checked: the people API watches the session, and the upgrade rebuilds the session (`encoreMode` is a final field of each session); the dev VM's Diagnostics log shows the Encore adapter chosen (`could not ask who I am`, an artefact of that VM). **The friend journey itself (J13) is still not walked.**
* **M3. The old request portal is still in the product.** `requests/` (a download-service sheet, a request chip on catalogue pages, `settings/requests_screen.dart` with "Test connection" and "Connect") and the same "Test connection" in `settings/your_server_screen.dart`. The ground rule is that nothing of the owner's homelab request portal belongs in Encore (P2-07 removes it); a person with an Encore server should never see it.
* **M4. "Play songs your server does not have" and "Switch on / Switched off" appear in two places** (`settings/encore_play_section.dart`, `settings/your_server_screen.dart`).
* **M5. "Ask for better quality"** in the ⋯ menu of a catalogue page (`catalogue/adding_music_help.dart`) is a request-portal action (M3).
* **M6. `settings/your_server_screen.dart` mixes the old setup with Encore**: eight of the ten rows that mention the portal, the old fetch service or the old people service are on this one page. What it shows depends on which kind of server it is; it must be read on each (J12).
* **M7. 42 controls had no handler in the scan.** Many are static rows or handlers set on a wrapper (false positives); each is a lead to check by tapping it. Examples to check first: "Ask for better quality", "How does this work?", "More for <member>" and "Play on <member>" in a Jam, "Change <person>" in People, "Share what I'm listening to".
* **M8. Settings > Appearance** offers a true-black switch in light mode (F42); **Settings and Library both offer "my music / the whole server"** (F41); **no screen offers friends or a profile to edit** (F43). Found by the owner, listed here so the review does not lose them.

## `common/` (20 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `common/collection_menu.dart:98` | ListTile | Play next | onTap () => queueAll(next: true), |  | |
| `common/collection_menu.dart:103` | ListTile | Add to queue | onTap () => queueAll(next: false), |  | |
| `common/collection_menu.dart:110` | ListTile | Add to playlist | onTap () { |  | |
| `common/collection_menu.dart:123` | ListTile | Rename playlist | onTap () { |  | |
| `common/collection_menu.dart:132` | ListTile | Delete playlist | onTap () async { |  | |
| `common/collection_menu.dart:144` | ListTile | Go to artist | onTap () { |  | |
| `common/connection_banner.dart:75` | TextButton | Try again | onPressed () => | DUP | |
| `common/download_button.dart:226` | ListTile | Try again now | onTap () => Navigator.of(context).pop(false), |  | |
| `common/download_button.dart:231` | ListTile |  | onTap () => Navigator.of(context).pop(true), |  | |
| `common/download_button.dart:241` | ListTile | Keep downloaded | onTap () => Navigator.of(context).pop(), |  | |
| `common/playlist_actions.dart:93` | TextButton | Cancel | onPressed () => Navigator.of(context).pop(), | DUP | |
| `common/playlist_actions.dart:97` | FilledButton |  | onPressed _submit |  | |
| `common/playlist_actions.dart:216` | ListTile | New playlist | onTap createNew | DUP | |
| `common/playlist_actions.dart:235` | ListTile |  | onTap () => addTo(p), |  | |
| `common/playlist_actions.dart:272` | TextButton | Cancel | onPressed () => Navigator.of(ctx).pop(false), | DUP | |
| `common/playlist_actions.dart:276` | FilledButton | Delete | onPressed () => Navigator.of(ctx).pop(true), |  | |
| `common/track_menu.dart:273` | ListTile |  | onTap enabled |  | |
| `common/widgets.dart:38` | TextButton |  | onPressed onSeeAll |  | |
| `common/widgets.dart:276` | IconButton | More options | onPressed onMore | DUP | |
| `common/widgets.dart:392` | FilledButton |  | onPressed onAction |  | |

## `detail/` (3 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `detail/detail_screens.dart:74` | IconButton | More options | onPressed tracks.isEmpty | DUP | |
| `detail/detail_screens.dart:90` | IconButton |  | onPressed tracks.isEmpty |  | |
| `detail/detail_screens.dart:403` | TextButton | Try again | onPressed () => ref | DUP | |

## `home/` (8 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `home/home_screen.dart:233` | IconButton |  | onPressed () => Nav.news(context), |  | |
| `home/home_screen.dart:246` | IconButton | Settings | onPressed () => Nav.settings(context), |  | |
| `home/home_screen.dart:262` | ActionChip | Jam | onPressed () => Nav.jam(context), |  | |
| `home/home_screen.dart:566` | FilledButton.icon | Search for a song | onPressed () => context.go('/search'), | DUP | |
| `home/home_screen.dart:572` | OutlinedButton.icon | Import a playlist or artist | onPressed () => context.push('/settings/import'), |  | |
| `home/home_screen.dart:578` | FilledButton.icon | Import a playlist or artist | onPressed () => context.push('/settings/import'), |  | |
| `home/home_screen.dart:584` | OutlinedButton.icon | Search and request | onPressed () => context.go('/search'), |  | |
| `home/home_screen.dart:592` | TextButton | What does my server need? | onPressed () => context.push('/settings/server'), |  | |

## `import/` (30 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `import/encore_import_screen.dart:259` | IconButton | Paste from clipboard | onPressed _busy | DUP | |
| `import/encore_import_screen.dart:319` | OutlinedButton.icon | Choose a file | onPressed _busy | DUP | |
| `import/encore_import_screen.dart:378` | ListTile | Stop | onTap onOpen | DUP | |
| `import/encore_import_screen.dart:400` | TextButton | Stop | onPressed onStop | DUP | |
| `import/import_card.dart:64` | IconButton | Got it | onPressed () => |  | |
| `import/import_card.dart:146` | TextButton |  | onPressed () => unawaited(_showMissing(context, ref)), |  | |
| `import/import_card.dart:156` | FilledButton.tonal |  | onPressed () => Nav.importedPlaylist(context, job.id), |  | |
| `import/import_card.dart:161` | FilledButton.tonal | Open playlist | onPressed () => Nav.playlist(context, playlist), |  | |
| `import/import_card.dart:166` | FilledButton.tonal | Open liked songs | onPressed () => Nav.liked(context), |  | |
| `import/import_card.dart:171` | TextButton | Stop | onPressed () => unawaited(_confirmStop(context, ref)), | DUP | |
| `import/import_card.dart:189` | TextButton | Keep going | onPressed () => Navigator.of(dialog).pop(false), |  | |
| `import/import_card.dart:193` | TextButton | Stop | onPressed () => Navigator.of(dialog).pop(true), | DUP | |
| `import/import_card.dart:224` | ListTile | The list is not available right now. | - | NOOP? | |
| `import/import_card.dart:227` | ListTile | ${song.artist}${song.message.isEmpty ?  | - | NOOP? | |
| `import/import_card.dart:274` | InkWell | Importing ${jobs.length} playlists: $done of  | onTap () => context.push('/settings/import'), |  | |
| `import/import_screen.dart:57` | ListTile | Your server's song service needs an update | - | NOOP? | |
| `import/import_screen.dart:373` | IconButton | Paste from clipboard | onPressed phase | DUP | |
| `import/import_screen.dart:399` | FilledButton.icon |  | onPressed phase |  | |
| `import/import_screen.dart:432` | OutlinedButton.icon | Choose a file | onPressed phase | DUP | |
| `import/import_screen.dart:497` | CheckboxListTile | ${plural(_fileEntries[i].tracks.length,  | onChanged starting |  | |
| `import/import_screen.dart:523` | FilledButton.icon |  | onPressed starting |  | |
| `import/import_screen.dart:536` | TextButton | Choose another file | onPressed starting |  | |
| `import/import_screen.dart:646` | FilledButton.icon |  | onPressed starting |  | |
| `import/import_screen.dart:660` | TextButton | Choose another link | onPressed starting |  | |
| `import/imported_playlist_screen.dart:55` | FilledButton | Try again | onPressed () => | DUP | |
| `import/imported_playlist_screen.dart:143` | OutlinedButton | Open in library | onPressed () => Nav.playlist(context, job.playlistId!), |  | |
| `import/imported_playlist_screen.dart:240` | ListTile | Don't import this song | onTap () async { |  | |
| `import/imported_playlist_screen.dart:260` | ListTile | Being fetched right now | - | NOOP? | |
| `import/imported_playlist_screen.dart:267` | ListTile | To take it off the playlist | - | NOOP? | |
| `import/imported_playlist_screen.dart:274` | ListTile | Open the playlist in your library | onTap () { |  | |

## `jam/` (12 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `jam/add_songs_sheet.dart:169` | ListTile |  | onTap added |  | |
| `jam/jam_screen.dart:82` | FilledButton.icon | Start a Jam | onPressed busy |  | |
| `jam/jam_screen.dart:109` | FilledButton | Join | onPressed busy |  | |
| `jam/jam_screen.dart:196` | FilledButton.icon | Add songs | onPressed () => unawaited(showAddSongsSheet(context)), |  | |
| `jam/jam_screen.dart:214` | OutlinedButton | End Jam for everybody | onPressed () => unawaited(_confirmEnd(context, controller)), |  | |
| `jam/jam_screen.dart:219` | OutlinedButton | Leave Jam | onPressed () => unawaited(controller.leave()), |  | |
| `jam/jam_screen.dart:237` | TextButton | Cancel | onPressed () => Navigator.of(context).pop(false), | DUP | |
| `jam/jam_screen.dart:241` | FilledButton | End Jam | onPressed () => Navigator.of(context).pop(true), |  | |
| `jam/jam_screen.dart:287` | IconButton | Copy the code | onPressed () async { |  | |
| `jam/jam_screen.dart:388` | ListTile | More for ${member.name} | - | NOOP? | |
| `jam/jam_screen.dart:411` | PopupMenuItem | Play on ${member.name}\ | - | NOOP? | |
| `jam/jam_screen.dart:415` | PopupMenuItem | Remove from the Jam | - | NOOP? | |

## `library/` (10 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `library/library_screen.dart:154` | IconButton | Search | onPressed () => context.go('/search'), |  | |
| `library/library_screen.dart:159` | IconButton | Create | onPressed () => unawaited(_showCreateSheet(context)), |  | |
| `library/library_screen.dart:186` | TextButton.icon |  | onPressed () => |  | |
| `library/library_screen.dart:199` | IconButton |  | onPressed () => |  | |
| `library/library_screen.dart:265` | ListTile | New playlist | onTap () { | DUP | |
| `library/library_screen.dart:274` | ListTile | Import from Spotify or YouTube Music | onTap () { |  | |
| `library/library_screen.dart:609` | TextButton |  | onPressed () => ref |  | |
| `library/library_screen.dart:651` | FilledButton | Search for a song | onPressed () => context.go('/search'), | DUP | |
| `library/library_screen.dart:655` | OutlinedButton | Browse the whole server | onPressed () => ref |  | |
| `library/library_screen.dart:708` | ListTile | ${plural(songs,  | onTap () => Nav.downloaded(context), |  | |

## `onboarding/` (9 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `onboarding/connect_screen.dart:233` | TextButton.icon | Got a setup link? Paste it | onPressed _busy |  | |
| `onboarding/connect_screen.dart:274` | IconButton |  | onPressed () => setState(() => _obscure = !_obscure), |  | |
| `onboarding/connect_screen.dart:309` | TextButton | Add another address (for when  | onPressed _busy |  | |
| `onboarding/connect_screen.dart:325` | FilledButton |  | onPressed _busy |  | |
| `onboarding/join_screen.dart:273` | IconButton |  | onPressed () => setState(() => _obscure = !_obscure), |  | |
| `onboarding/join_screen.dart:291` | FilledButton |  | onPressed _busy |  | |
| `onboarding/join_screen.dart:313` | TextButton | I already have an account | onPressed _busy |  | |
| `onboarding/join_screen.dart:368` | FilledButton | Try again | onPressed onRetry | DUP | |
| `onboarding/join_screen.dart:374` | TextButton | I already have an account | onPressed () => context.go('/onboarding'), |  | |

## `people/` (13 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `people/invite_dialog.dart:150` | FilledButton |  | onPressed _busy |  | |
| `people/invite_dialog.dart:215` | TextButton | Revoke | onPressed () => unawaited(_revoke(row.id)), |  | |
| `people/invite_dialog.dart:227` | TextButton | Close | onPressed () => Navigator.of(context).pop(), | DUP | |
| `people/invite_dialog.dart:232` | TextButton.icon | Copy link | onPressed () async { | DUP | |
| `people/invite_dialog.dart:245` | FilledButton.icon | Share | onPressed () async { |  | |
| `people/people_screen.dart:79` | TextButton | Cancel | onPressed () => Navigator.of(context).pop(false), | DUP | |
| `people/people_screen.dart:83` | FilledButton | Make owner | onPressed () => Navigator.of(context).pop(true), |  | |
| `people/people_screen.dart:102` | TextButton | Cancel | onPressed () => Navigator.of(context).pop(false), | DUP | |
| `people/people_screen.dart:106` | FilledButton | Remove | onPressed () => Navigator.of(context).pop(true), | DUP | |
| `people/people_screen.dart:138` | ListTile | Invite someone | onTap () => unawaited(showDialog<void>( | DUP | |
| `people/people_screen.dart:171` | TextButton | Try again | onPressed () => ref.invalidate(peopleDirectoryProvider), | DUP | |
| `people/people_screen.dart:222` | ListTile | Change ${person.user} | - | NOOP? | |
| `people/share_listening_tile.dart:19` | SwitchListTile | Share what I'm listening to | - | NOOP? | |

## `player/` (19 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `player/lyrics_screen.dart:157` | IconButton | Close | onPressed () => context.pop(), | DUP | |
| `player/lyrics_screen.dart:302` | IconButton | Close lyrics | onPressed onClose |  | |
| `player/lyrics_screen.dart:353` | IconButton | Previous | onPressed onPrevious | DUP | |
| `player/lyrics_screen.dart:366` | IconButton | Next | onPressed onNext | DUP | |
| `player/now_playing_screen.dart:44` | IconButton | Close | onPressed () => context.pop(), | DUP | |
| `player/now_playing_screen.dart:173` | IconButton | Close player | onPressed () => context.pop(), |  | |
| `player/now_playing_screen.dart:193` | IconButton | More options | onPressed () async { | DUP | |
| `player/now_playing_screen.dart:325` | IconButton |  | onPressed session |  | |
| `player/now_playing_screen.dart:375` | IconButton |  | onPressed facade.toggleShuffle |  | |
| `player/now_playing_screen.dart:382` | IconButton | Previous | onPressed facade.skipPrevious | DUP | |
| `player/now_playing_screen.dart:423` | IconButton | Next | onPressed snapshot.hasNext | DUP | |
| `player/now_playing_screen.dart:429` | IconButton |  | onPressed facade.cycleRepeat |  | |
| `player/now_playing_screen.dart:454` | IconButton | Choose where to play | onPressed () async { |  | |
| `player/now_playing_screen.dart:467` | IconButton | Queue | onPressed () => showQueueSheet(context), |  | |
| `player/now_playing_screen.dart:542` | InkWell | Lyrics | onTap () => Nav.lyrics(context), |  | |
| `player/queue_sheet.dart:66` | TextButton | Save | onPressed () => unawaited(_saveAsPlaylist( |  | |
| `player/queue_sheet.dart:78` | TextButton | Clear | onPressed () => unawaited(facade.clearUpNext()), | DUP | |
| `player/queue_sheet.dart:198` | ListTile |  | onTap onTap |  | |
| `player/sleep_timer_sheet.dart:51` | ListTile |  | onTap () { |  | |

## `profiles/` (4 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `profiles/profiles_screen.dart:28` | IconButton | Back | onPressed () => context.go('/home'), |  | |
| `profiles/profiles_screen.dart:56` | ListTile | Add someone | onTap () => context.push('/profiles/add'), |  | |
| `profiles/profiles_screen.dart:97` | ListTile | More about ${profile.username} | onTap onPick |  | |
| `profiles/profiles_screen.dart:112` | PopupMenuItem | Remove from this device | - | NOOP? | |

## `requests/` (8 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `requests/download_service_sheet.dart:286` | TextButton | I don't have one | onPressed _noService |  | |
| `requests/download_service_sheet.dart:341` | FilledButton | Connect | onPressed _chosen | DUP | |
| `requests/download_service_sheet.dart:348` | TextButton | Use another address | onPressed () => setState(() => _phase = _Phase.typing), |  | |
| `requests/download_service_sheet.dart:373` | FilledButton.icon | Search my network | onPressed _search |  | |
| `requests/download_service_sheet.dart:378` | OutlinedButton | Type the address | onPressed () => setState(() => _phase = _Phase.typing), |  | |
| `requests/download_service_sheet.dart:401` | TextButton | Cancel | onPressed () { | DUP | |
| `requests/download_service_sheet.dart:428` | FilledButton | Check and connect | onPressed _checkTyped |  | |
| `requests/download_service_sheet.dart:464` | FilledButton | Sign in | onPressed () => |  | |

## `search/` (4 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `search/search_results.dart:503` | Chip | In your library | - | NOOP? DUP | |
| `search/search_screen.dart:125` | IconButton | Clear | onPressed () { | DUP | |
| `search/search_screen.dart:199` | TextButton | Clear | onPressed () => | DUP | |
| `search/search_screen.dart:210` | ListTile |  | onTap () => onRecent(recents[i]), |  | |

## `settings/` (109 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `settings/diagnostics_screen.dart:113` | IconButton | Run a background sync pass now | onPressed () async { |  | |
| `settings/diagnostics_screen.dart:124` | IconButton | Send a test notification | onPressed () async { |  | |
| `settings/diagnostics_screen.dart:146` | IconButton | Copy report | onPressed () async { |  | |
| `settings/diagnostics_screen.dart:162` | SwitchListTile | Show a performance counter | onChanged ref.read(settingsProvider.notifier) |  | |
| `settings/encore_play_section.dart:32` | ListTile | Switched off | - | NOOP? DUP | |
| `settings/encore_play_section.dart:40` | ListTile | Asking your server... | - | NOOP? | |
| `settings/encore_play_section.dart:49` | ListTile | Taking a short rest | - | NOOP? | |
| `settings/encore_play_section.dart:58` | ListTile | Not available on this server | - | NOOP? | |
| `settings/encore_play_section.dart:65` | ListTile | Ready | - | NOOP? | |
| `settings/encore_play_section.dart:78` | SwitchListTile | Play songs your server does not have | onChanged ref.read(settingsProvider.notifier) | DUP | |
| `settings/encore_play_section.dart:91` | ListTile | Your server did not answer | - | NOOP? | |
| `settings/equalizer_screen.dart:39` | SwitchListTile | Equalizer | onChanged service.setEnabled | DUP | |
| `settings/equalizer_screen.dart:115` | TextButton.icon | Reset to flat | onPressed service.reset |  | |
| `settings/failed_edits.dart:48` | ListTile | The server turned them down. Try again, or let them go. | onPressed actions.retryAll |  | |
| `settings/failed_edits.dart:55` | TextButton | Try all again | onPressed actions.retryAll |  | |
| `settings/failed_edits.dart:62` | ListTile | Try again | onPressed () => actions.retry(edit.id), | DUP | |
| `settings/failed_edits.dart:70` | IconButton | Try again | onPressed () => actions.retry(edit.id), | DUP | |
| `settings/failed_edits.dart:75` | IconButton | Let it go | onPressed () => actions.discard(edit.id), |  | |
| `settings/household_settings_screen.dart:24` | ListTile |  | onTap () => notifier.setLibraryScope(scope), |  | |
| `settings/household_settings_screen.dart:59` | SwitchListTile | Show "New on the server" | onChanged notifier.setShowNewOnServer |  | |
| `settings/household_settings_screen.dart:68` | SwitchListTile | Private listening | onChanged notifier.setPrivateListening |  | |
| `settings/household_settings_screen.dart:78` | ListTile | Signed in as ${server?.username ??  | - | NOOP? | |
| `settings/import_screen.dart:208` | ListTile | Adding music is switched off | onPressed () { |  | |
| `settings/import_screen.dart:214` | TextButton | Switch on | onPressed () { | DUP | |
| `settings/import_screen.dart:223` | ListTile | Your server needs its download service | onPressed _connect |  | |
| `settings/import_screen.dart:231` | TextButton | Connect | onPressed _connect | DUP | |
| `settings/import_screen.dart:251` | IconButton | Paste from clipboard | onPressed _paste | DUP | |
| `settings/import_screen.dart:288` | FilledButton.icon |  | onPressed backend |  | |
| `settings/import_screen.dart:337` | ListTile | Nothing imported yet | - | NOOP? | |
| `settings/import_screen.dart:377` | TextButton | Cancel | onPressed () => Navigator.of(dialog).pop(false), | DUP | |
| `settings/import_screen.dart:381` | TextButton | Remove | onPressed () => Navigator.of(dialog).pop(true), | DUP | |
| `settings/import_screen.dart:515` | ListTile | Remove import | onTap playlist |  | |
| `settings/import_screen.dart:543` | IconButton | Remove import | onPressed onRemove |  | |
| `settings/import_screen.dart:603` | ListTile | Stop tracking ${artist.name} | onTap asked |  | |
| `settings/import_screen.dart:625` | ActionChip |  | onPressed () async { |  | |
| `settings/import_screen.dart:639` | IconButton | Stop tracking ${artist.name} | onPressed () async { |  | |
| `settings/invite_someone.dart:63` | ListTile | Invite someone | onTap () { | DUP | |
| `settings/invite_someone.dart:90` | ListTile | People | onTap () => context.push('/settings/people'), |  | |
| `settings/invite_someone.dart:141` | TextButton | Close | onPressed () => Navigator.of(context).pop(), | DUP | |
| `settings/invite_someone.dart:145` | FilledButton.icon | Copy link | onPressed () async { | DUP | |
| `settings/notifications_screen.dart:33` | SwitchListTile | New on your server | - | NOOP? | |
| `settings/notifications_screen.dart:44` | SwitchListTile | New releases you do not have | - | NOOP? | |
| `settings/notifications_screen.dart:57` | SwitchListTile | Imports and requests | - | NOOP? | |
| `settings/playback_settings_screen.dart:46` | ListTile | Equalizer | onTap () => context.push('/settings/equalizer'), | DUP | |
| `settings/playback_settings_screen.dart:53` | ListTile | Volume levelling | - | NOOP? | |
| `settings/playback_settings_screen.dart:79` | SwitchListTile | Quiet places | onChanged ctrl.setReplayGainBoost |  | |
| `settings/requests_screen.dart:73` | ListTile |  | onPressed () async { | MODE | |
| `settings/requests_screen.dart:82` | TextButton |  | onPressed () async { | MODE | |
| `settings/requests_screen.dart:90` | SwitchListTile | Show Request and Import | onChanged ref.read(settingsProvider.notifier) |  | |
| `settings/requests_screen.dart:99` | ListTile | Test connection | onTap _testing | DUP | |
| `settings/requests_screen.dart:128` | ListTile | Nothing requested yet | - | NOOP? | |
| `settings/server_addresses.dart:119` | TextButton | Cancel | onPressed () => Navigator.of(context).pop(false), | DUP | |
| `settings/server_addresses.dart:123` | FilledButton | Remove | onPressed () => Navigator.of(context).pop(true), | DUP | |
| `settings/server_addresses.dart:176` | ListTile | Remove ${e.label} | onPressed () => _remove(server, endpoints, e), |  | |
| `settings/server_addresses.dart:188` | IconButton | Remove ${e.label} | onPressed () => _remove(server, endpoints, e), |  | |
| `settings/server_addresses.dart:196` | ListTile | Add an address | onTap () => _add(server, endpoints), |  | |
| `settings/server_addresses.dart:203` | ListTile | Check addresses | onTap () => _test(server, endpoints), |  | |
| `settings/server_addresses.dart:290` | TextButton | Cancel | onPressed () => Navigator.of(context).pop(), | DUP | |
| `settings/server_addresses.dart:294` | FilledButton | Add | onPressed _submit |  | |
| `settings/settings_page.dart:83` | ListTile |  | onTap () async { |  | |
| `settings/settings_page.dart:101` | ListTile |  | onTap () => Navigator.of(sheet).pop(q), |  | |
| `settings/settings_screens.dart:162` | ListTile |  | onTap () => context.push(g.route), |  | |
| `settings/settings_screens.dart:178` | ListTile | Switch user | onTap () => context.push('/profiles'), |  | |
| `settings/settings_screens.dart:187` | ListTile | Sign out | onTap () => unawaited(confirmAndSignOut(context, ref)), | DUP | |
| `settings/settings_screens.dart:335` | SwitchListTile | True black background | onChanged ctrl.setAmoled |  | |
| `settings/settings_screens.dart:357` | ListTile | Text size | onChanged ctrl.setLyricsTextScale |  | |
| `settings/settings_screens.dart:369` | SwitchListTile | Keep screen on | onChanged ctrl.setKeepScreenOnInLyrics |  | |
| `settings/settings_screens.dart:396` | ListTile | Songs on this device | - | NOOP? | |
| `settings/settings_screens.dart:400` | ListTile | Last sync | - | NOOP? | |
| `settings/settings_screens.dart:415` | ListTile | Last attempt did not finish | - | NOOP? | |
| `settings/settings_screens.dart:421` | ListTile | Sync while the app is closed | onTap () async { |  | |
| `settings/settings_screens.dart:436` | ListTile |  | onTap () => Navigator.of(context).pop(h), |  | |
| `settings/settings_screens.dart:454` | ListTile | Sync now | onTap () => session?.scheduler.requestSync(force: false), |  | |
| `settings/settings_screens.dart:461` | ListTile | Rebuild library | onTap () => session?.scheduler.requestSync(force: true), |  | |
| `settings/settings_screens.dart:516` | SwitchListTile | Download over Wi-Fi only | onChanged ctrl.setWifiOnlyDownloads |  | |
| `settings/settings_screens.dart:535` | ListTile | Storage limit | onTap () async { |  | |
| `settings/settings_screens.dart:552` | ListTile | ${e.kind} • ${AudioQuality.byId(e.pin.quality).label} | onPressed () async { |  | |
| `settings/settings_screens.dart:557` | IconButton | Remove download | onPressed () async { |  | |
| `settings/settings_screens.dart:572` | TextButton.icon | Remove all downloads? | onPressed () async { |  | |
| `settings/settings_screens.dart:585` | TextButton | Cancel | onPressed () => Navigator.of(dialog).pop(false), | DUP | |
| `settings/settings_screens.dart:589` | FilledButton | Remove | onPressed () => Navigator.of(dialog).pop(true), | DUP | |
| `settings/settings_screens.dart:634` | ListTile |  | onTap () => Navigator.of(context).pop(_LimitChoice(bytes)), |  | |
| `settings/settings_screens.dart:654` | ListTile | Version ${AppBranding.version} | - | NOOP? | |
| `settings/settings_screens.dart:658` | ListTile | Open-source licences | onTap () => showLicensePage( |  | |
| `settings/settings_screens.dart:668` | ListTile | Diagnostics | onTap () => Navigator.of(context).push(MaterialPageRoute<void>( |  | |
| `settings/shrink_notice.dart:33` | ListTile | Your server lists far fewer songs than before | - | NOOP? | |
| `settings/shrink_notice.dart:47` | TextButton | Follow the server? | onPressed session |  | |
| `settings/shrink_notice.dart:60` | TextButton | Cancel | onPressed () => Navigator.pop(context, false), | DUP | |
| `settings/shrink_notice.dart:64` | TextButton | Follow the server | onPressed () => Navigator.pop(context, true), |  | |
| `settings/sign_out.dart:102` | TextButton | Cancel | onPressed () => Navigator.of(dialog).pop(false), | DUP | |
| `settings/sign_out.dart:106` | FilledButton | Sign out | onPressed () => Navigator.of(dialog).pop(true), | DUP | |
| `settings/your_server_screen.dart:75` | ListTile | ${plural(tracks,  | - | NOOP? | |
| `settings/your_server_screen.dart:91` | ListTile | Switched off | onPressed () async { | MODE DUP | |
| `settings/your_server_screen.dart:96` | TextButton | Switch on | onPressed () async { | MODE DUP | |
| `settings/your_server_screen.dart:108` | ListTile | Not set up | onPressed () async { | MODE | |
| `settings/your_server_screen.dart:115` | TextButton | Find it | onPressed () async { | MODE | |
| `settings/your_server_screen.dart:190` | ListTile | Switched off | - | NOOP? DUP | |
| `settings/your_server_screen.dart:198` | ListTile | Looking next to your music server... | - | NOOP? | |
| `settings/your_server_screen.dart:206` | ListTile | Ready - ${uri.host}:${uri.port} | onPressed () => _askAddress(context, ref), |  | |
| `settings/your_server_screen.dart:213` | TextButton | Change | onPressed () => _askAddress(context, ref), |  | |
| `settings/your_server_screen.dart:223` | SwitchListTile | Play songs your server does not have | onChanged notifier.setInstantPlayEnabled | DUP | |
| `settings/your_server_screen.dart:238` | ListTile | Not found | onPressed () => ref.invalidate(fetchServiceProvider), | MODE | |
| `settings/your_server_screen.dart:245` | TextButton | Look again | onPressed () => ref.invalidate(fetchServiceProvider), | MODE | |
| `settings/your_server_screen.dart:249` | TextButton | Type | onPressed () => _askAddress(context, ref), |  | |
| `settings/your_server_screen.dart:272` | TextButton | Cancel | onPressed () => Navigator.of(dialog).pop(), | DUP | |
| `settings/your_server_screen.dart:276` | TextButton | Check | onPressed () => Navigator.of(dialog).pop(controller.text), |  | |
| `settings/your_server_screen.dart:349` | ListTile | Connected - $where | onPressed () async { | MODE | |
| `settings/your_server_screen.dart:356` | TextButton | Change | onPressed () async { | MODE | |
| `settings/your_server_screen.dart:364` | ListTile | Test connection | onTap _testing | DUP | |

## `year/` (2 controls)

| File:line | Kind | Label | Handler | Flags | Verdict |
|-----------|------|-------|---------|-------|---------|
| `year/year_screen.dart:342` | ListTile |  | onTap song.albumId |  | |
| `year/year_screen.dart:381` | ListTile |  | onTap id |  | |
