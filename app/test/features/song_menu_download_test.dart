import 'package:drift/drift.dart' show Value;
import 'package:encore/app/notifications.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/common/widgets.dart';
import 'package:encore/features/downloads/download_notifications_prompt.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// D-26 and D-32 (F31, F49): a long press on a song row opens the song's menu, and the menu can download that one song, or take it off the
/// phone again, without touching the playlist or album it is in.
void main() {
  setUpAll(loadAppFonts);
  setUp(() =>
      SharedPreferences.setMockInitialValues({'encore.libraryScope': 'mine'}));

  Future<void> open(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  Future<void> pin(AppDatabase db, int serverId, String type, String id) =>
      db.into(db.pins).insert(PinsCompanion.insert(
            serverId: serverId,
            targetType: type,
            targetId: id,
            createdAtMs: 1,
          ));

  Future<void> onPhone(AppDatabase db, int serverId, String trackId) =>
      db.into(db.downloads).insert(DownloadsCompanion.insert(
            serverId: serverId,
            trackId: trackId,
            state: const Value(2),
            localPath: Value('/x/$trackId.opus'),
            bytes: const Value(5 * 1024 * 1024),
            updatedAtMs: 0,
          ));

  Future<void> longPressFirstSong(WidgetTester tester) async {
    await tester.longPress(find.byType(TrackTile).first);
    await settle(tester);
  }

  testWidgets('a long press on a song row opens the song menu', (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await open(tester, '/home/album/al1');

    await longPressFirstSong(tester);

    expect(find.text('Add to playlist'), findsOneWidget);
    expect(find.text('Add to Liked Songs'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('the menu offers Download, and choosing it pins that one song',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await open(tester, '/home/album/al1');
    await longPressFirstSong(tester);

    expect(find.text('Remove download'), findsNothing);
    await tester.tap(find.text('Download'));
    await settle(tester);

    final pins = await app.db.select(app.db.pins).get();
    expect(pins.map((p) => (p.targetType, p.targetId)), [('track', 'al1-t1')],
        reason: 'only this song, not the album');
    expect(find.textContaining('Downloading'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'Download in the song menu asks once about download progress after the menu has closed; "Not now" is final (D-52)',
      (tester) async {
    final phone = _AskingNotifications();
    final app = await pumpApp(tester,
        size: const Size(390, 1400),
        overrides: [localNotificationsProvider.overrideWithValue(phone)]);
    await open(tester, '/home/album/al1');
    await longPressFirstSong(tester);

    await tester.tap(find.text('Download'));
    await settle(tester);

    final pins = await app.db.select(app.db.pins).get();
    expect(pins.map((p) => (p.targetType, p.targetId)), [('track', 'al1-t1')],
        reason: 'the download started first');
    expect(find.text('Add to playlist'), findsNothing,
        reason: 'the menu has closed');
    expect(find.text(DownloadNotificationsPage.title), findsOneWidget,
        reason: 'and the question still came, although the menu is gone');
    expect(phone.asked, 0, reason: 'the phone is asked only on "Allow"');

    await tester.tap(find.text('Not now'));
    await settle(tester);
    expect(find.text(DownloadNotificationsPage.title), findsNothing);

    // The next Download, from another song's menu: the download goes ahead and nothing is asked.
    await tester.longPress(find.byType(TrackTile).at(1));
    await settle(tester);
    await tester.tap(find.text('Download'));
    await settle(tester);
    expect(find.text(DownloadNotificationsPage.title), findsNothing);
    expect(phone.asked, 0);
    expect((await app.db.select(app.db.pins).get()).length, 2);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song with its own download offers Remove download, and choosing it takes it off',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await pin(app.db, app.serverId, 'track', 'al1-t1');
    await onPhone(app.db, app.serverId, 'al1-t1');
    await open(tester, '/home/album/al1');
    await longPressFirstSong(tester);

    expect(find.text('Download'), findsNothing);
    await tester.tap(find.text('Remove download'));
    await settle(tester);

    expect(await app.db.select(app.db.pins).get(), isEmpty);
    expect(find.textContaining('Removed'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'taking off a song that is also in a downloaded playlist says it stays on the phone, not "Removed" (advisor)',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await pin(app.db, app.serverId, 'track', 'al1-t1');
    await pin(
        app.db, app.serverId, 'playlist', 'pl2'); // Late night: al1-t1 ...
    await onPhone(app.db, app.serverId, 'al1-t1');
    await open(tester, '/home/album/al1');
    await longPressFirstSong(tester);

    await tester.tap(find.text('Remove download'));
    await settle(tester);

    final pins = await app.db.select(app.db.pins).get();
    expect(pins.map((p) => (p.targetType, p.targetId)), [('playlist', 'pl2')],
        reason: 'only the choice made for this song is undone');
    expect(find.textContaining('stays on this phone'), findsOneWidget,
        reason: 'the playlist still wants it: it did not leave');
    expect(find.textContaining('Removed'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song that is on the phone only because of its playlist says so, and offers no second download',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await pin(
        app.db, app.serverId, 'playlist', 'pl2'); // Late night: al1-t1 ...
    await onPhone(app.db, app.serverId, 'al1-t1');
    await open(tester, '/home/album/al1');
    await longPressFirstSong(tester);

    expect(find.text('Downloaded'), findsOneWidget);
    expect(find.textContaining('with its playlist or album'), findsOneWidget);
    expect(find.text('Download'), findsNothing);
    expect(find.text('Remove download'), findsNothing,
        reason: 'it would not leave the phone: the playlist still wants it');
    await closeApp(tester, app.db);
  });
}

/// A phone that has not been asked yet (Android 13 or newer, permission not granted).
class _AskingNotifications extends LocalNotifications {
  int asked = 0;

  @override
  Future<bool> areAllowed() async => false;

  @override
  Future<bool> requestPermission() async {
    asked++;
    return true;
  }
}
