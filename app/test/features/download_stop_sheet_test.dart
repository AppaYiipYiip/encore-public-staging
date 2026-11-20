import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/domain/download_line.dart';
import 'package:encore/features/common/download_button.dart';
import 'package:encore/features/downloads/download_line_providers.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// N-39 (docs/design S-96, S-17): the sheet of a download. "Stop" is its own row and keeps the files; "Remove download" is always the removal and asks
/// first, in the words drawn; the Download button has a state of its own while a download is stopped. Today's sheet had one destructive row, "Stop
/// and remove download", that deleted the files with one tap: so "Stop" meant delete (PB-40).
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  const coming = DownloadLine(
    '12 of 217 on this phone · 40 ready on your server',
    phoneFraction: 12 / 217,
    twoStages: true,
    canStop: true,
  );
  const stopped = DownloadLine(
    'Stopped · 12 of 217 on this phone · 40 ready on your server',
    phoneFraction: 12 / 217,
    twoStages: true,
    stopped: true,
  );
  // 340 MB on this phone, 12 of 217 songs.
  const stateComing = PinState(
      pinned: true, total: 217, done: 12, active: 205, bytes: 340 * 1048576);
  const stateStopped = PinState(
      pinned: true,
      total: 217,
      done: 12,
      active: 205,
      bytes: 340 * 1048576,
      stopped: true);
  const stateDone =
      PinState(pinned: true, total: 217, done: 217, bytes: 6350 * 1048576);

  late _Actions actions;

  Future<void> open(
    WidgetTester tester, {
    required PinState state,
    required DownloadLine line,
    String name = 'Prog snob',
    Future<String?> Function()? onRemove,
  }) async {
    actions = _Actions();
    await tester.pumpWidget(ProviderScope(
      overrides: [
        downloadActionsProvider.overrideWithValue(actions),
        downloadLineProvider.overrideWith((ref, t) => line),
      ],
      child: MaterialApp(
        theme:
            buildEncoreTheme(EncoreColors.dark(), brightness: Brightness.dark),
        home: Scaffold(
          body: Center(
            child: DownloadButton(
              type: PinTargetType.playlist,
              targetId: 'pl_1',
              name: name,
              stateOverride: state,
              onRemove: onRemove,
            ),
          ),
        ),
      ),
    ));
    await tester.pump();
    await tester.tap(find.byType(DownloadButton));
    await tester.pumpAndSettle();
  }

  group('the sheet while songs are coming (S-96)', () {
    testWidgets(
        'N-39: Stop is its own row and says what is kept; Remove download says it asks; Keep downloaded closes the sheet',
        (tester) async {
      await open(tester, state: stateComing, line: coming);

      expect(find.text('Prog snob'), findsOneWidget);
      expect(find.textContaining('Stop'), findsWidgets);
      expect(find.text('Stop'), findsOneWidget);
      expect(
          find.text(
              'Keeps the 12 songs on this phone. Your server goes on saving the rest.'),
          findsOneWidget);
      expect(find.text('Remove download'), findsOneWidget);
      expect(
          find.text('Takes this download off this phone. You are asked first.'),
          findsOneWidget);
      expect(find.text('Keep downloaded'), findsOneWidget);
      expect(find.text('Stop and remove download'), findsNothing,
          reason: '"Stop" no longer means delete');
      expect(find.text('Resume'), findsNothing);
    });

    testWidgets(
        'N-39: pressing Stop stops the download, asks nothing, and removes nothing',
        (tester) async {
      await open(tester, state: stateComing, line: coming);

      await tester.tap(find.text('Stop'));
      await tester.pumpAndSettle();

      expect(actions.stopped, [
        [(PinTargetType.playlist, 'pl_1')]
      ]);
      expect(actions.unpinned, isEmpty);
      expect(find.byType(AlertDialog), findsNothing);
    });
  });

  group('the sheet of a stopped download (S-96)', () {
    testWidgets(
        'N-39: Resume stands where Stop stood, with its own line, and there is no "Try again now"',
        (tester) async {
      await open(tester, state: stateStopped, line: stopped);

      expect(
          find.text(
              'Stopped · 12 of 217 on this phone · 40 ready on your server - 217 songs, 340.0 MB on this phone'),
          findsOneWidget);
      expect(find.text('Resume'), findsOneWidget);
      expect(find.text('Copies the rest to this phone.'), findsOneWidget);
      expect(find.text('Stop'), findsNothing);
      expect(find.text('Try again now'), findsNothing);
      expect(find.text('Remove download'), findsOneWidget);

      await tester.tap(find.text('Resume'));
      await tester.pumpAndSettle();

      expect(actions.resumed, [
        [(PinTargetType.playlist, 'pl_1')]
      ]);
      expect(actions.unpinned, isEmpty);
    });
  });

  group('the question before Remove (S-96)', () {
    testWidgets(
        'N-39: Remove asks first, in the words drawn: what is deleted, what is kept, and that it can be downloaded again',
        (tester) async {
      await open(tester, state: stateStopped, line: stopped);

      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();

      expect(find.text('Remove Prog snob from this phone?'), findsOneWidget);
      expect(
          find.text(
              'The 12 songs on this phone (340.0 MB) are deleted, and the rest will not be downloaded.'),
          findsOneWidget);
      expect(
          find.text(
              'Your music stays on your server and you can download it again. A song that another download also has stays on this phone.'),
          findsOneWidget);
      expect(find.text('Cancel'), findsOneWidget);
      expect(find.text('Remove'), findsOneWidget);
      expect(actions.unpinned, isEmpty,
          reason: 'nothing is deleted until the person says so');
    });

    testWidgets('N-39: Cancel in the dialog changes nothing', (tester) async {
      await open(tester, state: stateComing, line: coming);

      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(actions.unpinned, isEmpty);
      expect(actions.stopped, isEmpty);
      expect(actions.resumed, isEmpty);
      expect(find.byType(AlertDialog), findsNothing);
    });

    testWidgets(
        'N-39: Remove in the dialog is the one thing that deletes: it takes the download off the phone',
        (tester) async {
      await open(tester, state: stateComing, line: coming);

      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();

      expect(actions.unpinned, ['playlist:pl_1']);
      expect(find.text('Removed Prog snob from this phone'), findsOneWidget);
    });

    testWidgets(
        'N-39: a finished download says "The 217 songs on this phone (6.20 GB) are deleted." with no "rest"',
        (tester) async {
      await open(tester,
          state: stateDone,
          line: const DownloadLine('Downloaded • 217 songs',
              phoneFraction: 1, complete: true, twoStages: true));

      expect(find.text('Stop'), findsNothing,
          reason: 'a finished download has nothing to stop');
      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();

      expect(find.text('The 217 songs on this phone (6.20 GB) are deleted.'),
          findsOneWidget);
      expect(find.textContaining('the rest'), findsNothing);
    });

    testWidgets(
        'N-39: a release (its own removal) asks the same question, and Cancel never reaches it',
        (tester) async {
      var removed = 0;
      await open(tester, state: stateComing, line: coming, onRemove: () async {
        removed++;
        return null;
      });

      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(removed, 0);

      await tester.tap(find.byType(DownloadButton));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();
      expect(removed, 1);
      expect(actions.unpinned, isEmpty);
    });
  });

  group('the Download button of a stopped download (S-17)', () {
    testWidgets(
        'N-39: a solid ring with a pause mark, not the ring that turns, and a name a screen reader can use',
        (tester) async {
      actions = _Actions();
      await tester.pumpWidget(ProviderScope(
        overrides: [
          downloadActionsProvider.overrideWithValue(actions),
          downloadLineProvider.overrideWith((ref, t) => stopped),
        ],
        child: MaterialApp(
          theme: buildEncoreTheme(EncoreColors.dark(),
              brightness: Brightness.dark),
          home: const Scaffold(
            body: Center(
              child: DownloadButton(
                type: PinTargetType.playlist,
                targetId: 'pl_1',
                name: 'Prog snob',
                stateOverride: stateStopped,
              ),
            ),
          ),
        ),
      ));
      await tester.pump();

      expect(find.byIcon(Icons.pause_rounded), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing,
          reason: 'it is not the ring that turns');
      // Exactly the drawing's label (S-17: `aria-label="Stopped, 12 of 220 on this phone. Tap for options"`), with this test's numbers: a pattern here
      // let "Stopped. Stopped · 12 of 217 on this phone · 40 ready on your server. Tap for options" through, which a screen reader reads twice.
      expect(
          find.bySemanticsLabel(
              'Stopped, 12 of 217 on this phone. Tap for options'),
          findsOneWidget);
    });

    testWidgets(
        'N-39: the screen-reader label of a stopped download is the same sentence with or without the server\'s half, and says only what is on the phone',
        (tester) async {
      actions = _Actions();
      await tester.pumpWidget(ProviderScope(
        overrides: [
          downloadActionsProvider.overrideWithValue(actions),
          downloadLineProvider.overrideWith((ref, t) => const DownloadLine(
              'Stopped · 1 of 4 on this phone',
              phoneFraction: 0.25,
              twoStages: true,
              stopped: true)),
        ],
        child: MaterialApp(
          theme: buildEncoreTheme(EncoreColors.dark(),
              brightness: Brightness.dark),
          home: const Scaffold(
            body: Center(
              child: DownloadButton(
                type: PinTargetType.playlist,
                targetId: 'pl_1',
                name: 'Prog snob',
                stateOverride: PinState(
                    pinned: true, total: 4, done: 1, active: 3, stopped: true),
              ),
            ),
          ),
        ),
      ));
      await tester.pump();

      expect(
          find.bySemanticsLabel(
              'Stopped, 1 of 4 on this phone. Tap for options'),
          findsOneWidget);
    });
  });
}

class _Actions implements DownloadActions {
  final List<List<PinKey>> stopped = [];
  final List<List<PinKey>> resumed = [];
  final List<String> unpinned = [];

  @override
  Future<void> pin(PinTargetType type, String targetId,
      {AudioQuality? quality, List<String> alongside = const []}) async {}

  @override
  Future<void> unpin(PinTargetType type, String targetId) async =>
      unpinned.add('${type.name}:$targetId');

  @override
  Future<void> retry() async {}

  @override
  Future<void> stop(List<PinKey> pins) async => stopped.add(pins);

  @override
  Future<void> resume(List<PinKey> pins) async => resumed.add(pins);

  @override
  Future<void> removeAll() async {}
}
