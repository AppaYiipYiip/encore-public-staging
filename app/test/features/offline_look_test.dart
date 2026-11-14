import 'dart:async';

import 'package:drift/drift.dart' show Value;
import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// P1-15 (R2-F5): the phone says it is offline once, in a strip that goes after a few seconds (D-45), and **after that the screens still show
/// what cannot be played**: grey, with "Not downloaded" in words (S-10, S-14, S-17, S-18). That look follows the lasting state of the
/// connection, not the strip, and goes by itself when the connection is back.
void main() {
  setUpAll(loadAppFonts);

  const offlineStrip = "You're offline. Nothing can play until you reconnect.";

  /// A phone whose network can be switched: starts with none.
  (StreamController<NetworkKind>, List<Override>) network(
      {Set<String> downloaded = const {}}) {
    // Closed by each test that asks for it.
    // ignore: close_sinks
    final changes = StreamController<NetworkKind>.broadcast();
    return (
      changes,
      [
        connectionGraceProvider.overrideWithValue(Duration.zero),
        // The strip is said for one second here instead of five.
        connectionShownForProvider
            .overrideWithValue(const Duration(seconds: 1)),
        networkKindProvider.overrideWith((ref) async* {
          yield NetworkKind.none;
          yield* changes.stream;
        }),
        downloadedIdsProvider.overrideWith((ref) => Stream.value(downloaded)),
      ]
    );
  }

  Future<void> open(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  testWidgets(
      'R2-F5: Home keeps its grey "Not downloaded" look after the strip has gone, and loses it by itself when the connection is back',
      (tester) async {
    final (changes, overrides) = network();
    final app = await pumpApp(tester, overrides: overrides);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    expect(find.text(offlineStrip), findsOneWidget,
        reason: 'the strip says it once');
    expect(find.text('Not downloaded'), findsWidgets);
    // Liked Songs is not judged as a whole (as drawn: its own page greys the songs one by one).
    final likedTile = find
        .ancestor(of: find.text('Liked Songs'), matching: find.byType(InkWell))
        .first;
    expect(
        find.descendant(of: likedTile, matching: find.text('Not downloaded')),
        findsNothing);

    await tester
        .pump(const Duration(seconds: 2)); // longer than the strip stays
    await settle(tester);
    expect(find.textContaining("You're offline"), findsNothing,
        reason: 'the strip has gone, as D-45 decided');
    expect(find.text('Not downloaded'), findsWidgets,
        reason: 'but the screen still shows what cannot be played');

    changes.add(NetworkKind.wifi);
    await settle(tester);
    expect(find.text('Not downloaded'), findsNothing,
        reason: 'back online: the look leaves by itself');
    await changes.close();
    await closeApp(tester, app.db);
  });

  testWidgets(
      "CN-4b: with a network but a silent server the strip says 'Can't reach your server.' once, and the same lasting look follows",
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      connectionGraceProvider.overrideWithValue(Duration.zero),
      connectionShownForProvider.overrideWithValue(const Duration(seconds: 1)),
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.wifi)),
      serverFindingProvider
          .overrideWith((ref) => Stream.value(ServerFinding.silent)),
      downloadedIdsProvider.overrideWith((ref) => Stream.value(<String>{})),
    ]);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    expect(find.text("Can't reach your server."), findsOneWidget);
    expect(find.textContaining("You're offline"), findsNothing);
    expect(find.text('Not downloaded'), findsWidgets);

    await tester.pump(const Duration(seconds: 2));
    await settle(tester);
    expect(find.textContaining("Can't reach"), findsNothing,
        reason: 'said once');
    expect(find.text('Not downloaded'), findsWidgets,
        reason: 'the lasting look stays while the server is silent');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'at text size 200 % the offline Home tiles hold two lines and nothing overflows',
      (tester) async {
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    final (changes, overrides) = network();
    final app = await pumpApp(tester,
        overrides: overrides, size: const Size(390, 1400));
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);
    await tester.pump(const Duration(seconds: 2));
    await settle(tester);

    expect(tester.takeException(), isNull, reason: 'no overflow at 200 % text');
    expect(find.text('Not downloaded'), findsWidgets);
    await changes.close();
    await closeApp(tester, app.db);
  });

  testWidgets('online, nothing on Home says "Not downloaded"', (tester) async {
    final app = await pumpApp(tester, overrides: [
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.wifi)),
      downloadedIdsProvider.overrideWith((ref) => Stream.value(<String>{})),
    ]);
    await settle(tester);

    expect(find.text('Not downloaded'), findsNothing);
    expect(find.text('Plays offline'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a playlist that is on the phone keeps its colour and is listed under "Downloaded, Plays offline"',
      (tester) async {
    final (changes, overrides) = network(downloaded: {'al1-t1', 'al2-t3'});
    final app = await pumpApp(tester, overrides: overrides);
    await app.db.into(app.db.pins).insert(PinsCompanion.insert(
          serverId: app.serverId,
          targetType: 'playlist',
          targetId: 'pl2',
          createdAtMs: 1,
        ));
    for (final id in ['al1-t1', 'al2-t3']) {
      await app.db.into(app.db.downloads).insert(DownloadsCompanion.insert(
            serverId: app.serverId,
            trackId: id,
            state: const Value(2),
            localPath: Value('/x/$id.opus'),
            bytes: const Value(1024),
            updatedAtMs: 0,
          ));
    }
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);
    await tester.pump(const Duration(seconds: 2));
    await settle(tester);

    expect(find.text('Plays offline'), findsOneWidget);
    expect(find.text('Late night'), findsWidgets,
        reason: 'the downloaded playlist is on the shelf');
    await changes.close();
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a download that was pressed and has no file yet is not "Plays offline", and its card says "Not downloaded" (a tunnel)',
      (tester) async {
    final (changes, overrides) = network();
    final app = await pumpApp(tester, overrides: overrides);
    await app.db.into(app.db.pins).insert(PinsCompanion.insert(
          serverId: app.serverId,
          targetType: 'playlist',
          targetId: 'pl2',
          createdAtMs: 1,
        ));
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);
    await tester.pump(const Duration(seconds: 2));
    await settle(tester);

    expect(find.text('Plays offline'), findsNothing,
        reason: 'nothing of it is on the phone');
    expect(find.text('Not downloaded'), findsWidgets);
    await changes.close();
    await closeApp(tester, app.db);
  });

  testWidgets(
      'an album that is on the phone only because a pinned playlist holds one of its songs keeps its colour in the Library (one definition of "on the phone")',
      (tester) async {
    final (changes, overrides) = network(downloaded: {'al1-t1'});
    final app = await pumpApp(tester, overrides: overrides);
    await app.db.into(app.db.pins).insert(PinsCompanion.insert(
          serverId: app.serverId,
          targetType: 'playlist',
          targetId: 'pl2', // Late night: al1-t1, al2-t3, al2-t4
          createdAtMs: 1,
        ));
    await app.db.into(app.db.downloads).insert(DownloadsCompanion.insert(
          serverId: app.serverId,
          trackId: 'al1-t1',
          state: const Value(2),
          localPath: const Value('/x/al1-t1.opus'),
          bytes: const Value(1024),
          updatedAtMs: 0,
        ));
    await tester.pump(const Duration(milliseconds: 50));
    await open(tester, '/library');
    await tester.tap(find.text('Albums').last);
    await settle(tester);

    // Six albums; Kodama (al1) has a song on the phone through the playlist and no pin of its own.
    final kodama = find
        .ancestor(of: find.text('Kodama'), matching: find.byType(InkWell))
        .first;
    expect(find.descendant(of: kodama, matching: find.text('Not downloaded')),
        findsNothing,
        reason: 'a song of it is on the phone: it plays');
    final blackwater = find
        .ancestor(
            of: find.text('Blackwater Park'), matching: find.byType(InkWell))
        .first;
    expect(
        find.descendant(of: blackwater, matching: find.text('Not downloaded')),
        findsOneWidget);
    await changes.close();
    await closeApp(tester, app.db);
  });

  testWidgets(
      'offline, an album page says "Not downloaded" in words on the songs that cannot be played, and nothing else changes',
      (tester) async {
    final (changes, overrides) = network(downloaded: {'al1-t2'});
    final app = await pumpApp(tester,
        overrides: overrides, size: const Size(390, 1400));
    await open(tester, '/home/album/al1');

    // Five songs, one on the phone.
    expect(find.text('Not downloaded'), findsNWidgets(4));
    expect(find.byIcon(Icons.cloud_off_rounded), findsAtLeastNWidgets(4),
        reason: 'the existing dimming and icon stay beside the words');
    await changes.close();
    await closeApp(tester, app.db);
  });

  testWidgets(
      'offline, the Library lists playlists that are not on the phone as "Not downloaded"',
      (tester) async {
    final (changes, overrides) = network();
    final app = await pumpApp(tester, overrides: overrides);
    await tester.pump(const Duration(milliseconds: 50));
    await open(tester, '/library');
    await tester.tap(find.text('Playlists').last);
    await settle(tester);

    expect(find.text('Not downloaded'), findsWidgets);
    await changes.close();
    await closeApp(tester, app.db);
  });
}
