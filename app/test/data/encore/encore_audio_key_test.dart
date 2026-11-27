// N-38 (docs/tasks/N-38-audio-only-key.md section 4): what the app reads of the server's `file.audioKey`, and the key it makes of a song when there is none.
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/encore/encore_writer.dart';
import 'package:encore/data/sync/fingerprint.dart';
import 'package:flutter_test/flutter_test.dart';

const _served = 'a1:0123456789abcdef0123456789abcdef';

Map<String, dynamic> _refJson({Object? audioKey, Map<String, dynamic>? meta}) =>
    {
      'id': 'sr_${'a' * 26}',
      'title': 'Weird Fishes',
      'artists': ['Radiohead'],
      'durationMs': 200000,
      'file': {
        'id': 'sf_1',
        'navidromeSongId': 'nd1',
        'codec': 'flac',
        'bitrateKbps': 900,
        'meta': meta ??
            {
              'size': 5000,
              'suffix': 'flac',
              'samplingRate': 44100,
              'bitDepth': 16,
            },
        if (audioKey != null) 'audioKey': audioKey,
      },
    };

void main() {
  group('EncoreFile', () {
    test('reads the key of the audio when the server serves one', () {
      expect(EncoreRef.fromJson(_refJson(audioKey: _served)).file!.audioKey,
          _served);
    });

    test('has no key on a server from before', () {
      expect(EncoreRef.fromJson(_refJson()).file!.audioKey, isNull);
    });

    test(
        'keeps whatever string the server sends; whether it is a key of the servers kind is decided where it is used',
        () {
      expect(EncoreRef.fromJson(_refJson(audioKey: 'x')).file!.audioKey, 'x');
      expect(isServerAudioKey('x'), isFalse);
      expect(isServerAudioKey(_served), isTrue);
    });
  });

  group('the old formula is frozen', () {
    test('its digest of known properties never changes', () {
      // If this changes, every phone's stored key stops matching and every downloaded song is fetched again. Change the formula only with a migration.
      expect(
        legacyAudioKey(
          size: 5000,
          suffix: 'flac',
          bitRate: 900,
          durationSec: 200,
          samplingRate: 44100,
          bitDepth: 16,
        ),
        '0140ae32952f109d95afc5cfbb0d34b1',
      );
    });
  });

  group('refAudioKey', () {
    test('is the served key, as it is', () {
      expect(refAudioKey(EncoreRef.fromJson(_refJson(audioKey: _served))),
          _served);
    });

    test('is the old formula\'s key when no key is served', () {
      final ref = EncoreRef.fromJson(_refJson());
      expect(refAudioKey(ref), '0140ae32952f109d95afc5cfbb0d34b1');
      expect(refAudioKey(ref), refLegacyAudioKey(ref));
    });

    test('a key that is not of the server\'s kind is not taken for one', () {
      final ref = EncoreRef.fromJson(_refJson(audioKey: 'something-else'));
      expect(refAudioKey(ref), refLegacyAudioKey(ref));
    });

    test('a song with no file has no key', () {
      final ref = EncoreRef.fromJson({
        'id': 'sr_${'b' * 26}',
        'title': 'x',
        'artists': ['y'],
      });
      expect(refAudioKey(ref), '');
      expect(refLegacyAudioKey(ref), '');
    });

    test(
        'a tag rewrite (another size) leaves the served key alone and changes the old key',
        () {
      final before = EncoreRef.fromJson(_refJson(audioKey: _served));
      final after = EncoreRef.fromJson(_refJson(audioKey: _served, meta: {
        'size': 5321,
        'suffix': 'flac',
        'samplingRate': 44100,
        'bitDepth': 16,
      }));
      expect(refAudioKey(after), refAudioKey(before));
      expect(refLegacyAudioKey(after), isNot(refLegacyAudioKey(before)));
    });
  });

  test(
      'the row the app writes for a ref holds the columns the old key is made of: adoption depends on it',
      () async {
    final db = AppDatabase(NativeDatabase.memory());
    addTearDown(db.close);
    final serverId = await db.into(db.servers).insert(ServersCompanion.insert(
        name: 'T', username: 'u', endpointsJson: '[]', createdAtMs: 0));
    final ref = EncoreRef.fromJson(_refJson(audioKey: _served));

    await EncoreWriter(db, serverId, ownerName: 'tester').upsertRefs([ref]);

    final row = await (db.select(db.tracks)
          ..where((t) => t.serverId.equals(serverId)))
        .getSingle();
    expect(row.audioKey, _served,
        reason: 'the key the server serves is stored');
    expect(
      legacyAudioKey(
        size: row.size,
        suffix: row.suffix,
        bitRate: row.bitRate,
        durationSec: row.durationSec,
        samplingRate: row.samplingRate,
        bitDepth: row.bitDepth,
      ),
      refLegacyAudioKey(ref),
      reason:
          'the columns of the row give the old key the app made before: what a copy downloaded earlier is compared with',
    );
  });
}
