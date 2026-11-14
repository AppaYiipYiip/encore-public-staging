import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/db/search_dao.dart';
import 'package:flutter_test/flutter_test.dart';

/// Audit B-84 (6 Nov 2026), written down as tests that are SKIPPED on purpose: what the phone's own search (the one Search offline,
/// P1-16, shows its results from) does not find outside the Latin alphabet. The cause is the tokenizer in `app_database.dart` (FTS5
/// `unicode61 remove_diacritics 2`) and the word rule of `toFtsQuery` (`search_dao.dart`: split on anything that is not a letter or a
/// number). The fix is P2-25 / the note on P2-12, not P1-16: when it lands, remove each `skip:` and the test must pass as it stands.
///
/// Each test is what a person does: types a word of a title written in their script and expects that song, and no other.
void main() {
  late AppDatabase db;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home server',
          username: 'marwa',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
  });
  tearDown(() => db.close());

  Future<void> add(String id, String title) =>
      db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: id,
            title: title,
            artist: const Value('Artist'),
          ));

  Future<List<String>> found(String typed) async =>
      [for (final t in await SearchDao(db).tracks(serverId, typed).get()) t.id];

  const gap = 'B-84: the local full-text index cannot do this yet (P2-25)';

  test('Hindi: a whole word is found, and only the songs that have it',
      skip: gap, () async {
    await add('hi-1', 'संगीत की दुनिया');
    // Its vowel signs are separators for the index: सागर तट is cut into स ग र and त ट, and the typed word संगीत into स ग त, so it matches.
    await add('hi-2', 'सागर तट');

    expect(await found('संगीत'), ['hi-1']);
  });

  test('Thai: a word inside a title is found', skip: gap, () async {
    await add('th-1', 'เพลงรัก ของเรา');

    expect(await found('รัก'), ['th-1']);
  });

  test('Japanese: a word inside a title is found', skip: gap, () async {
    await add('ja-1', '夜に駆ける');

    expect(await found('駆ける'), ['ja-1']);
  });

  test('Chinese: a word inside a title is found', skip: gap, () async {
    await add('zh-1', '我的中国心');

    expect(await found('中国'), ['zh-1']);
  });

  test(
      'Arabic: a word typed without the vowel marks finds the title written with them',
      skip: gap, () async {
    await add('ar-1', 'مَرْحَبًا بالعالم');

    expect(await found('مرحبا'), ['ar-1']);
  });
}
