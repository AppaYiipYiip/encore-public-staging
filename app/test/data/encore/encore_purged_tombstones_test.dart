import 'dart:convert';
import 'dart:io';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/encore/encore_writer.dart';
import 'package:flutter_test/flutter_test.dart';

/// N-31 (N-27 slice 2d), the phone's side of what the server now says (docs/17 "Playlists and entries that are gone"): the server purges removed entries and
/// the entries of deleted playlists after 90 days, and a phone that was away is told from the change log: a playlist whose row is gone as `{id, deleted: true}`,
/// an entry as `{id, playlist, deleted: true}`. This test reads the real response the server's own test saved (`library-changes-with-purged-tombstones.json`)
/// and applies it, so that the contract is proved on both sides. It changes no app code: the phone already reads these items.
const _live = 'pl_aaaaaaaaaaaaaaaaaaaaaaaaaa';
const _deleted = 'pl_bbbbbbbbbbbbbbbbbbbbbbbbbb';
const _missing = 'pl_cccccccccccccccccccccccccc';
const _removed = 'pe_xxxxxxxxxxxxxxxxxxxxxxxxxx';
const _inDeleted = 'pe_yyyyyyyyyyyyyyyyyyyyyyyyyy';
const _noPlaylist = 'pe_zzzzzzzzzzzzzzzzzzzzzzzzzz';

void main() {
  late AppDatabase db;
  late EncoreWriter writer;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Test',
          username: 'tester',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    writer = EncoreWriter(db, serverId, ownerName: 'tester');
  });
  tearDown(() => db.close());

  EncoreChanges fixture() => EncoreChanges.fromJson(jsonDecode(
      File('test/fixtures/server/library-changes-with-purged-tombstones.json')
          .readAsStringSync()) as Map<String, dynamic>);

  Future<void> playlist(String id) =>
      db.into(db.playlists).insertOnConflictUpdate(PlaylistsCompanion.insert(
            serverId: serverId,
            id: id,
            name: 'List $id',
          ));

  Future<void> entry(String playlistId, String entryId, int position) =>
      db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
            serverId: serverId,
            playlistId: playlistId,
            position: position,
            trackId: 'sr_$entryId',
            entryId: Value(entryId),
            serverPosition: Value(position.toDouble()),
          ));

  Future<Set<String>> entries() async => {
        for (final e in await db.select(db.playlistEntries).get())
          if (e.entryId != null) e.entryId!
      };

  Future<PlaylistRow?> row(String id) => (db.select(db.playlists)
        ..where((p) => p.serverId.equals(serverId) & p.id.equals(id)))
      .getSingleOrNull();

  test(
      'the parser reads a deleted playlist whose row is kept, one that exists nowhere ({id, deleted}) and the entries, from the file the server wrote',
      () {
    final page = fixture();

    expect(page.playlists.map((p) => (p.id, p.name, p.deleted)), [
      (_live, 'Keepers', false),
      (_deleted, 'Old mix', true),
      (_missing, '', true),
    ]);
    expect(page.entries.map((e) => (e.id, e.playlist, e.deleted)), [
      (_removed, _live, true),
      (_inDeleted, _deleted, true),
      (_noPlaylist, '', true),
    ]);
  });

  test(
      'applying it: the purged removal is dropped by its id because the server names its playlist, the deleted playlists lose their entries, a live entry stays',
      () async {
    for (final p in [_live, _deleted, _missing]) {
      await playlist(p);
    }
    await entry(_live, _removed, 0);
    await entry(_live, 'pe_keeper000000000000000000', 1);
    await entry(_deleted, _inDeleted, 0);
    await entry(_missing, 'pe_other0000000000000000000', 0);

    final page = fixture();
    await writer.applyPlaylists(page.playlists, page.entries, nowMs: 1000);

    expect(await entries(), {'pe_keeper000000000000000000'});
    expect((await row(_live))?.deletedAtMs, isNull);
    expect((await row(_deleted))?.deletedAtMs, 1000,
        reason: 'a deleted playlist is marked deleted');
    expect((await row(_missing))?.deletedAtMs, 1000,
        reason:
            'a playlist the server says exists nowhere is deleted too: {id, deleted: true} is enough');
    expect((await row(_live))?.songCount, 1,
        reason: 'the live playlist is counted again without the removed entry');
  });

  test(
      'an entry that names no playlist is skipped by the phone, which is why the server always names it when it knows it',
      () async {
    await playlist(_live);
    await entry(_live, _noPlaylist, 0);

    final page = fixture();
    await writer.applyPlaylists(const [], page.entries, nowMs: 1000);

    expect(await entries(), contains(_noPlaylist),
        reason:
            'today an entry with no playlist is not applied (encore_writer.dart): the server must send the playlist (change_log.parent)');
  });
}
