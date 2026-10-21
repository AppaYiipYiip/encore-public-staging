import 'dart:async';

import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/jam/jam_providers.dart';
import 'package:encore/features/jam/jam_speaker.dart';
import 'package:encore/features/jam/jam_wiring.dart';
import 'package:encore/features/player/now_playing_screen.dart';
import 'package:encore_session/encore_session.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../../support/fake_jam_api.dart';
import '../../support/test_app.dart';

/// The Jam screen is what the owner could not find or use ("I still do not know
/// how to make a jam session"). Each test is a sentence a person would say, and
/// asserts what they would see: how to start, how to join, who is in it, what is
/// queued and by whom, who plays, how to leave.
class _AlwaysPlays implements JamSongPlayer {
  @override
  Future<bool> play(QueueEntry entry) async => true;

  @override
  bool alreadyPlaying(QueueEntry entry) => false;

  @override
  Future<void> preload(QueueEntry entry) async {}
}

void main() {
  setUpAll(loadAppFonts);

  late FakeJamApi api;
  String? clipboard;

  setUp(() {
    clipboard = null;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        clipboard = (call.arguments as Map)['text'] as String?;
      }
      return null;
    });
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null);
  });

  Future<AppDatabase> open(
    WidgetTester tester, {
    FakeJamApi? with_,
    bool hubThere = true,
  }) async {
    api = with_ ?? FakeJamApi();
    final app = await pumpApp(tester, size: const Size(390, 1800), overrides: [
      jamApiProvider.overrideWith((ref) async => hubThere ? api : null),
      jamBackoffProvider.overrideWithValue(const [Duration(milliseconds: 1)]),
      jamClockEveryProvider.overrideWithValue(const Duration(days: 1)),
      // The speaker's own work is tested in jam_speaker_test; here it just plays.
      jamSongPlayerProvider.overrideWithValue(_AlwaysPlays()),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/home/jam'));
    await settle(tester);
    return app.db;
  }

  Future<void> start(WidgetTester tester) async {
    await tester.tap(find.text('Start a Jam'));
    await settle(tester);
  }

  const owner = Member(id: 'owner', name: 'owner', role: Role.host);
  const mia = Member(id: 'mia', name: 'mia');

  SessionState session({
    List<QueueEntry> queue = const [],
    int index = 0,
    bool playing = false,
    String? player,
    int rev = 5,
    List<Member> members = const [owner, mia],
  }) =>
      SessionState(
          rev: rev,
          members: members,
          queue: queue,
          index: index,
          playing: playing,
          playerDeviceId: player);

  const sommaire = QueueEntry(
      uid: 1, trackId: 'a', addedBy: 'mia', title: 'Sommaire', artist: 'Raid');
  const kodama = QueueEntry(
      uid: 2,
      trackId: 'b',
      addedBy: 'owner',
      title: 'Opening',
      artist: 'Alcest');

  group('before a Jam', () {
    testWidgets('says what it is and offers to start or join', (tester) async {
      final db = await open(tester);

      expect(find.text('Jam'), findsWidgets);
      expect(find.text('Listen together'), findsOneWidget);
      expect(find.textContaining('One phone plays'), findsOneWidget);
      expect(find.text('Start a Jam'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Jam code'), findsOneWidget);
      expect(find.text('Join'), findsOneWidget);
      await closeApp(tester, db);
    });

    testWidgets(
        'a server without Jam says so and what to do, not a dead button',
        (tester) async {
      final db = await open(tester, hubThere: false);

      expect(find.textContaining('does not have Jam'), findsOneWidget);
      expect(find.textContaining('Listening together'), findsOneWidget,
          reason: 'it points at the step of the server guide');
      expect(find.text('Start a Jam'), findsNothing);
      await closeApp(tester, db);
    });
  });

  group('starting', () {
    testWidgets('shows the code, who is in it and who plays', (tester) async {
      final db = await open(tester);
      await start(tester);

      expect(find.text('AB23CD'), findsOneWidget);
      expect(find.textContaining('Playing on this phone'), findsOneWidget);
      expect(find.text('owner (you)'), findsOneWidget);
      expect(find.text('Host'), findsOneWidget);
      expect(find.text('Add songs'), findsOneWidget);
      expect(find.text('Nothing playing yet'), findsOneWidget);
      await closeApp(tester, db);
    });

    testWidgets('the code can be copied with how to use it', (tester) async {
      final db = await open(tester);
      await start(tester);

      await tester.tap(find.byTooltip('Copy the code'));
      await settle(tester);

      expect(clipboard, contains('AB23CD'));
      expect(clipboard, contains('Jam'));
      await closeApp(tester, db);
    });

    testWidgets('says why when the hub will not start one', (tester) async {
      final db = await open(tester);
      api.createAnswer = const Result.err(
          ServerFailure('The hub is full. Try again later.', statusCode: 503));

      await start(tester);

      expect(find.text('The hub is full. Try again later.'), findsWidgets);
      expect(find.text('Start a Jam'), findsOneWidget, reason: 'still there');
      await closeApp(tester, db);
    });
  });

  group('joining', () {
    testWidgets('a friend types the code and is in', (tester) async {
      final db = await open(tester, with_: FakeJamApi(me: 'mia'));

      await tester.enterText(
          find.widgetWithText(TextField, 'Jam code'), 'ab23cd');
      await tester.tap(find.text('Join'));
      await settle(tester);

      expect(api.joinedWith, ['ab23cd']);
      expect(find.text('AB23CD'), findsOneWidget);
      expect(find.textContaining('Playing on owner'), findsOneWidget,
          reason: 'the host\'s phone plays; hers is a remote');
      expect(find.text('Leave Jam'), findsOneWidget);
      expect(find.text('End Jam for everybody'), findsNothing,
          reason: 'only the host can end it');
      await closeApp(tester, db);
    });

    testWidgets('a wrong code says so and keeps the form', (tester) async {
      final db = await open(tester, with_: FakeJamApi(me: 'mia'));
      api.joinAnswer = const Result.err(
          NotFoundFailure('there is no session with that code'));

      await tester.enterText(
          find.widgetWithText(TextField, 'Jam code'), 'ZZZZZZ');
      await tester.tap(find.text('Join'));
      await settle(tester);

      expect(find.text('there is no session with that code'), findsWidgets);
      expect(find.text('Join'), findsOneWidget);
      await closeApp(tester, db);
    });
  });

  group('inside a Jam', () {
    testWidgets('the song on is a card that opens the player, with its queue',
        (tester) async {
      final db = await open(tester);
      await start(tester);

      api.pushState(session(queue: [sommaire, kodama], playing: true));
      await settle(tester);

      expect(find.text('Sommaire'), findsOneWidget);
      expect(find.text('Raid · 2 songs'), findsOneWidget);
      await tester.tap(find.text('Sommaire'));
      await settle(tester);
      expect(find.byType(NowPlayingScreen), findsOneWidget,
          reason: 'the ordinary player: the Jam is not a second one');
      await closeApp(tester, db);
    });

    testWidgets('with nothing in the Jam yet the card says how to start it',
        (tester) async {
      final db = await open(tester);
      await start(tester);

      expect(find.text('Nothing playing yet'), findsOneWidget);
      expect(find.textContaining('it plays in the Jam'), findsOneWidget);
      await closeApp(tester, db);
    });

    testWidgets('the host can send somebody away, a friend cannot',
        (tester) async {
      final db = await open(tester);
      await start(tester);
      api.pushState(session());
      await settle(tester);

      expect(find.byTooltip('More for mia'), findsOneWidget);
      api.commandAnswer = Result.ok(session(rev: 6, members: const [owner]));
      await tester.tap(find.byTooltip('More for mia'));
      await settle(tester);
      await tester.tap(find.text('Remove from the Jam'));
      await settle(tester);

      expect((api.commands.last.$2 as Kick).memberId, 'mia');
      await closeApp(tester, db);

      // And from a friend's phone there is no such menu.
      final db2 = await open(tester, with_: FakeJamApi(me: 'mia'));
      await tester.enterText(
          find.widgetWithText(TextField, 'Jam code'), 'AB23CD');
      await tester.tap(find.text('Join'));
      await settle(tester);
      expect(find.byTooltip('More for owner'), findsNothing);
      await closeApp(tester, db2);
    });

    testWidgets('the host picks whose phone plays', (tester) async {
      final db = await open(tester);
      await start(tester);
      api.pushState(session());
      await settle(tester);
      api.commandAnswer = Result.ok(session(rev: 6, player: 'mia'));

      await tester.tap(find.byTooltip('More for mia'));
      await settle(tester);
      await tester.tap(find.text('Play on mia\'s phone'));
      await settle(tester);

      expect((api.commands.last.$2 as Transfer).deviceId, 'mia');
      await closeApp(tester, db);
    });

    testWidgets('says when the connection blinked', (tester) async {
      final db = await open(tester);
      await start(tester);

      await api.drop();
      await tester.pump();
      await tester
          .pump(); // the stream's end is noticed, then the screen redraws

      expect(find.textContaining('Reconnecting'), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 30));
      api.pushState(session(rev: 8));
      await settle(tester);
      expect(find.textContaining('Reconnecting'), findsNothing);
      await closeApp(tester, db);
    });
  });

  group('leaving', () {
    testWidgets('a friend leaves and is back at the start', (tester) async {
      final db = await open(tester, with_: FakeJamApi(me: 'mia'));
      await tester.enterText(
          find.widgetWithText(TextField, 'Jam code'), 'AB23CD');
      await tester.tap(find.text('Join'));
      await settle(tester);

      await tester.tap(find.text('Leave Jam'));
      await settle(tester);

      expect(api.left, ['AB23CD']);
      expect(find.text('Start a Jam'), findsOneWidget);
      await closeApp(tester, db);
    });

    testWidgets('the host is asked before ending it for everybody',
        (tester) async {
      final db = await open(tester);
      await start(tester);

      await tester.tap(find.text('End Jam for everybody'));
      await settle(tester);
      expect(find.textContaining('Everybody is disconnected'), findsOneWidget);
      expect(api.left, isEmpty,
          reason: 'nothing happens until it is confirmed');

      await tester.tap(find.text('Cancel'));
      await settle(tester);
      expect(api.left, isEmpty);

      await tester.tap(find.text('End Jam for everybody'));
      await settle(tester);
      await tester.tap(find.text('End Jam'));
      await settle(tester);

      expect(api.left, ['AB23CD']);
      expect(find.text('Start a Jam'), findsOneWidget);
      await closeApp(tester, db);
    });

    testWidgets('when the host ends it, the friend is told and can start fresh',
        (tester) async {
      final db = await open(tester, with_: FakeJamApi(me: 'mia'));
      await tester.enterText(
          find.widgetWithText(TextField, 'Jam code'), 'AB23CD');
      await tester.tap(find.text('Join'));
      await settle(tester);

      api.pushState(session(rev: 20).copyWith(ended: true));
      await settle(tester);

      expect(find.textContaining('The Jam is over'), findsWidgets);
      expect(find.text('Start a Jam'), findsOneWidget);
      await closeApp(tester, db);
    });
  });
}
