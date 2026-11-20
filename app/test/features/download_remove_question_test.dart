import 'dart:async';

import 'package:drift/drift.dart' show Value;
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/domain/download_line.dart';
import 'package:encore/features/common/download_button.dart';
import 'package:encore/features/common/format.dart';
import 'package:encore/features/downloads/download_line_providers.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// N-39, review of PR 119 (S-96): THE QUESTION BEFORE REMOVE MUST BE TRUE WHEN IT IS ANSWERED. It used to be built from the state the Download button had when
/// the sheet OPENED, so songs that arrived meanwhile made "The 12 songs on this phone (340 MB) are deleted" untrue; and when the button was gone by the time
/// Remove was chosen (the page it stood on was left) the choice returned silently, with no question and no answer. Now the question reads the download as it
/// is NOW and follows it while it is open, and nothing after the sheet depends on the button being still on the screen.
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  const coming = DownloadLine(
    '12 of 217 on this phone · 40 ready on your server',
    phoneFraction: 12 / 217,
    twoStages: true,
    canStop: true,
  );

  PinState state(int done, {int total = 217, int mb = 1}) => PinState(
      pinned: true,
      total: total,
      done: done,
      active: total - done,
      bytes: mb * 1048576);

  group('the download button', () {
    late _LivePin live;
    late _Actions actions;
    late ValueNotifier<bool> showButton;

    Future<void> open(WidgetTester tester, PinState first) async {
      live = _LivePin(first);
      actions = _Actions();
      showButton = ValueNotifier(true);
      await tester.pumpWidget(ProviderScope(
        overrides: [
          downloadActionsProvider.overrideWithValue(actions),
          pinStateProvider.overrideWith((ref, key) => live.stream()),
          downloadLineProvider.overrideWith((ref, t) => coming),
        ],
        child: MaterialApp(
          theme: buildEncoreTheme(EncoreColors.dark(),
              brightness: Brightness.dark),
          home: Scaffold(
            body: Center(
              child: ValueListenableBuilder<bool>(
                valueListenable: showButton,
                builder: (_, shown, __) => shown
                    ? const DownloadButton(
                        type: PinTargetType.playlist,
                        targetId: 'pl_1',
                        name: 'Prog snob',
                      )
                    : const SizedBox.shrink(),
              ),
            ),
          ),
        ),
      ));
      await tester.pump();
      await tester.pump();
      await tester.tap(find.byType(DownloadButton));
      await tester.pumpAndSettle();
    }

    String deletes(int done, int mb) =>
        'The $done songs on this phone (${formatBytes(mb * 1048576)}) are deleted, and the rest will not be downloaded.';

    testWidgets(
        'N-39: songs that arrived while the sheet was open are in the question, not the number the sheet opened with',
        (tester) async {
      await open(tester, state(12, mb: 340));

      live.set(state(20, mb: 520));
      await tester.pump();
      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();

      expect(find.text(deletes(20, 520)), findsOneWidget);
      expect(find.text(deletes(12, 340)), findsNothing,
          reason: 'the number the sheet opened with is old');
    });

    testWidgets(
        'N-39: the question follows the download while it is open: what is on the phone when the person answers is what it says',
        (tester) async {
      await open(tester, state(12, mb: 340));
      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();
      expect(find.text(deletes(12, 340)), findsOneWidget);

      live.set(state(25, mb: 610));
      await tester.pump();
      await tester.pump();

      expect(find.text(deletes(25, 610)), findsOneWidget);
      expect(find.text(deletes(12, 340)), findsNothing);
      expect(actions.unpinned, isEmpty);

      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();
      expect(actions.unpinned, ['playlist:pl_1'],
          reason:
              'the removal takes the download as it is when it is confirmed, whatever the numbers said');
    });

    testWidgets(
        'N-39: a download that finished while the sheet was open is asked about as a finished one (no "rest")',
        (tester) async {
      await open(tester, state(200, mb: 300));

      live.set(state(217, mb: 330));
      await tester.pump();
      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();

      expect(
          find.text(
              'The 217 songs on this phone (${formatBytes(330 * 1048576)}) are deleted.'),
          findsOneWidget);
      expect(find.textContaining('the rest'), findsNothing);
    });

    testWidgets(
        'N-39: when the button is gone by the time Remove is chosen, the question is still asked and the answer still counts',
        (tester) async {
      await open(tester, state(12, mb: 340));

      // The page the button stood on was left while the sheet was open.
      showButton.value = false;
      await tester.pump();
      expect(find.byType(DownloadButton), findsNothing);
      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();

      expect(find.text('Remove Prog snob from this phone?'), findsOneWidget,
          reason: 'a choice made in the sheet must not vanish with the button');
      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();
      expect(actions.unpinned, ['playlist:pl_1']);
    });

    testWidgets(
        'N-39: when the button is gone by the time Cancel is pressed, nothing is removed',
        (tester) async {
      await open(tester, state(12, mb: 340));
      showButton.value = false;
      await tester.pump();
      await tester.tap(find.text('Remove download'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(actions.unpinned, isEmpty);
      expect(find.byType(AlertDialog), findsNothing);
    });

    testWidgets(
        'N-39: Stop chosen in the sheet still stops the download when the button is gone',
        (tester) async {
      await open(tester, state(12, mb: 340));
      showButton.value = false;
      await tester.pump();

      await tester.tap(find.text('Stop'));
      await tester.pumpAndSettle();

      expect(actions.stopped, [
        [(PinTargetType.playlist, 'pl_1')]
      ]);
    });
  });

  group('the trash button in Settings > Downloads and storage', () {
    testWidgets(
        'N-39: songs that land while the question is open are in it when it is answered',
        (tester) async {
      final app = await pumpApp(tester, size: const Size(390, 1400));
      await app.db.into(app.db.pins).insert(PinsCompanion.insert(
            serverId: app.serverId,
            targetType: 'album',
            targetId: 'al1',
            createdAtMs: 0,
          ));
      final tracks = await (app.db.select(app.db.tracks)
            ..where((t) => t.albumId.equals('al1')))
          .get();
      expect(tracks.length, greaterThanOrEqualTo(2));
      final element = tester.element(find.byType(Scaffold).first);
      GoRouter.of(element).go('/settings/downloads');
      await settle(tester);
      await tester.scrollUntilVisible(
          find.byTooltip('Remove download').first, 200,
          scrollable: find.byType(Scrollable).first);

      await tester.tap(find.byTooltip('Remove download').first);
      await settle(tester);
      expect(find.textContaining('No songs are on this phone yet'),
          findsOneWidget);

      // Two songs of the album reach the phone while the question is open.
      for (final t in tracks.take(2)) {
        await app.db.into(app.db.downloads).insert(DownloadsCompanion.insert(
              serverId: app.serverId,
              trackId: t.id,
              state: const Value(DownloadState.done),
              bytes: const Value(2 * 1048576),
              localPath: Value('/d/${t.id}'),
              updatedAtMs: 0,
            ));
      }
      await tester.pump(const Duration(milliseconds: 400));
      await settle(tester);

      expect(find.textContaining('The 2 songs on this phone'), findsOneWidget,
          reason: 'the question was built from what was there when it opened');
      expect(
          find.textContaining('No songs are on this phone yet'), findsNothing);
      await tester.tap(find.text('Cancel'));
      await settle(tester);
      await closeApp(tester, app.db);
    });
  });
}

/// The state of a download that can change while a sheet or a dialog is open.
class _LivePin {
  _LivePin(this.value);

  PinState value;
  final StreamController<PinState> _changes = StreamController.broadcast();

  Stream<PinState> stream() async* {
    yield value;
    yield* _changes.stream;
  }

  void set(PinState next) {
    value = next;
    _changes.add(next);
  }
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
