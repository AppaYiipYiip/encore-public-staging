import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../db/app_database.dart';
import '../encore/encore_models.dart' show EncoreSetItem;
import '../sync/sync_state_store.dart';

/// What this phone knows about one catalogue release it saved or downloaded (D-35).
@immutable
class PhoneRelease {
  const PhoneRelease({
    required this.refIds,
    this.title,
    this.artist,
    this.download = false,
  });

  /// The songs the server confirmed, in the release's order.
  final List<String> refIds;

  /// What Library > Downloaded shows for it, so it can be drawn offline.
  final String? title;
  final String? artist;

  /// The person asked for it on the phone too, not only on the server.
  final bool download;

  PhoneRelease copyWith({bool? download}) => PhoneRelease(
        refIds: refIds,
        title: title,
        artist: artist,
        download: download ?? this.download,
      );

  Map<String, Object?> toJson() => {
        'refs': refIds,
        if (title != null) 'title': title,
        if (artist != null) 'artist': artist,
        'download': download,
      };

  /// Tolerant: an entry that is not what it should be is skipped, never thrown on.
  static PhoneRelease? fromJson(Object? json) {
    if (json is! Map) return null;
    final refs = json['refs'];
    if (refs is! List) return null;
    return PhoneRelease(
      refIds: [
        for (final r in refs)
          if (r is String && r.isNotEmpty) r
      ],
      title: json['title'] is String ? json['title'] as String : null,
      artist: json['artist'] is String ? json['artist'] as String : null,
      download: json['download'] == true,
    );
  }
}

/// What the phone remembers about catalogue releases, in the per-server sync-state store, so that a release looks the same after a restart
/// (D-35). No schema of its own: the store is keyed by server and goes with the account when the person signs out.
///
/// Two entries that never share a key:
///  * **the set of saved releases**, owned by the sync: the server's `cat:<id>` saved albums (this is what shows "In your library" after a
///    restart, a reinstall and on a second phone);
///  * **this phone's release map**, owned by the release saver: what it saved and downloaded here, written when the server confirmed the
///    save and before the first song is pinned.
class ReleaseStore {
  ReleaseStore(AppDatabase db, int serverId)
      : _state = SyncStateStore(db, serverId);

  final SyncStateStore _state;

  static const savedKey = 'savedReleases';
  static const phoneKey = 'phoneReleases';

  Stream<Set<String>> watchSaved() => _state.watch(savedKey).map(_decodeSaved);

  Stream<Map<String, PhoneRelease>> watchPhone() =>
      _state.watch(phoneKey).map(_decodePhone);

  Future<Set<String>> saved() async => _decodeSaved(await _state.get(savedKey));

  Future<Map<String, PhoneRelease>> phone() async =>
      _decodePhone(await _state.get(phoneKey));

  /// The sync's side: the server's saved albums that are catalogue releases (`cat:<id>`); one the server no longer has is taken out.
  Future<void> applySaved(Iterable<EncoreSetItem> items) async {
    final releases = [
      for (final i in items)
        if (i.id.startsWith('cat:')) i
    ];
    if (releases.isEmpty) return;
    final now = await saved();
    for (final i in releases) {
      if (i.removed) {
        now.remove(i.id);
      } else {
        now.add(i.id);
      }
    }
    await _state.set(savedKey, jsonEncode(now.toList()..sort()));
  }

  /// The saver's side: this phone saved (and maybe downloaded) [releaseId].
  Future<void> put(String releaseId, PhoneRelease release) async {
    final all = await phone();
    all[releaseId] = release;
    await _writePhone(all);
  }

  /// The person took the downloaded copies off the phone: the release stays saved, without the intent to keep it here.
  Future<void> clearDownload(String releaseId) async {
    final all = await phone();
    final now = all[releaseId];
    if (now == null || !now.download) return;
    all[releaseId] = now.copyWith(download: false);
    await _writePhone(all);
  }

  /// The person took ONE song off the phone (the song menu): the phone's own record stops listing it, so the next start does not pin it
  /// again (D-35); a release left with no song is saved on the server without the intent to keep it here.
  Future<void> dropSong(String refId) async {
    final all = await phone();
    var changed = false;
    for (final e in all.entries.toList()) {
      if (!e.value.refIds.contains(refId)) continue;
      final left = [
        for (final r in e.value.refIds)
          if (r != refId) r
      ];
      all[e.key] = PhoneRelease(
        refIds: left,
        title: e.value.title,
        artist: e.value.artist,
        download: left.isEmpty ? false : e.value.download,
      );
      changed = true;
    }
    if (changed) await _writePhone(all);
  }

  Future<void> _writePhone(Map<String, PhoneRelease> all) => _state.set(
        phoneKey,
        jsonEncode({for (final e in all.entries) e.key: e.value.toJson()}),
      );

  static Set<String> _decodeSaved(String? raw) {
    if (raw == null) return <String>{};
    try {
      final list = jsonDecode(raw);
      if (list is! List) return <String>{};
      return {
        for (final id in list)
          if (id is String && id.isNotEmpty) id
      };
    } on FormatException {
      return <String>{};
    }
  }

  static Map<String, PhoneRelease> _decodePhone(String? raw) {
    if (raw == null) return <String, PhoneRelease>{};
    try {
      final map = jsonDecode(raw);
      if (map is! Map) return <String, PhoneRelease>{};
      return {
        for (final e in map.entries)
          if (e.key is String && PhoneRelease.fromJson(e.value) != null)
            e.key as String: PhoneRelease.fromJson(e.value)!,
      };
    } on FormatException {
      return <String, PhoneRelease>{};
    }
  }
}
