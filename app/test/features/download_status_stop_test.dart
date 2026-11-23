import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/domain/download_line.dart';
import 'package:encore/features/downloads/download_line_providers.dart';
import 'package:encore/features/downloads/download_status.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// N-39: Stop and Resume stand where Retry stands, in the download's own status (docs/design S-16 "Stop on a download that is coming", "Stopping",
/// "stopped, files kept, Resume", "a song interrupted from outside"; S-17). A text button under the line and the bar, in every place the status is
/// drawn; Stop asks no question; the stopped row has no Retry.
void main() {
  setUpAll(loadAppFonts);

  const target = DownloadTarget.pin(PinTargetType.playlist, 'pl_1');

  const coming = DownloadLine(
    '12 of 217 on this phone · 40 ready on your server',
    phoneFraction: 12 / 217,
    serverFraction: 40 / 217,
    twoStages: true,
    canStop: true,
  );
  const stoppedLine = DownloadLine(
    'Stopped · 12 of 217 on this phone · 40 ready on your server',
    phoneFraction: 12 / 217,
    serverFraction: 40 / 217,
    twoStages: true,
    stopped: true,
  );

  Future<
      ({
        List<DownloadTarget> stopped,
        List<DownloadTarget> resumed,
        List<DownloadTarget> retried
      })> show(
    WidgetTester tester, {
    DownloadLine? line,
    List<KeepFailure> failures = const [],
    bool showNames = false,
    double textScale = 1,
  }) async {
    final stopped = <DownloadTarget>[];
    final resumed = <DownloadTarget>[];
    final retried = <DownloadTarget>[];
    final overrides = <Override>[
      downloadLineProvider.overrideWith((ref, t) => line),
      keepFailuresProvider.overrideWith((ref, t) => failures),
      retryDownloadProvider.overrideWithValue((t) async => retried.add(t)),
      stopDownloadProvider.overrideWithValue((t) async => stopped.add(t)),
      resumeDownloadProvider.overrideWithValue((t) async => resumed.add(t)),
    ];
    // A new scope for each call: a scope that is only re-pumped keeps the providers it already built.
    await tester.pumpWidget(ProviderScope(
      key: UniqueKey(),
      overrides: overrides,
      child: MaterialApp(
        theme:
            buildEncoreTheme(EncoreColors.dark(), brightness: Brightness.dark),
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: TextScaler.linear(textScale)),
            child: child!),
        home: Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: DownloadStatus(target: target, showNames: showNames),
          ),
        ),
      ),
    ));
    await tester.pump();
    return (stopped: stopped, resumed: resumed, retried: retried);
  }

  testWidgets(
      'N-39: a download whose songs are coming has a Stop under its line, and one press stops it, with no question',
      (tester) async {
    final calls = await show(tester, line: coming);

    expect(find.text('Stop'), findsOneWidget);
    expect(find.text('Resume'), findsNothing);
    await tester.tap(find.text('Stop'));
    await tester.pump();

    expect(calls.stopped, [target]);
    expect(find.byType(AlertDialog), findsNothing,
        reason:
            'Stop deletes nothing and Resume undoes it: it asks no question');
    expect(calls.resumed, isEmpty);
  });

  testWidgets(
      'N-39: Stop is a 48 dp target with the words a screen reader needs',
      (tester) async {
    await show(tester, line: coming);

    final size = tester.getSize(find.widgetWithText(TextButton, 'Stop'));
    expect(size.height, greaterThanOrEqualTo(48));
    expect(find.bySemanticsLabel('Stop the download'), findsOneWidget);
  });

  testWidgets(
      'N-39: no Stop on a finished download, a plain music server\'s line, or a download with only songs that did not come (it keeps its Retry)',
      (tester) async {
    await show(tester,
        line: const DownloadLine('Downloaded • 9 songs',
            phoneFraction: 1, complete: true, twoStages: true));
    expect(find.text('Stop'), findsNothing);

    await show(tester, line: const DownloadLine('Downloading 4 of 10'));
    expect(find.text('Stop'), findsNothing);

    final calls = await show(tester,
        line: const DownloadLine('7 of 10 on this phone · 3 songs did not come',
            failed: 3, canRetry: true, twoStages: true, stuck: true));
    expect(find.text('Stop'), findsNothing);
    expect(find.text('Retry'), findsOneWidget);
    await tester.tap(find.text('Retry'));
    await tester.pump();
    expect(calls.retried, [target]);
  });

  testWidgets(
      'N-39: a stopped download says so, has Resume where Stop stood, and no Retry even with songs that did not come',
      (tester) async {
    final calls = await show(tester,
        line: const DownloadLine(
            'Stopped · 7 of 10 on this phone · 3 songs did not come',
            phoneFraction: 0.7,
            failed: 3,
            canRetry: false,
            twoStages: true,
            stopped: true),
        showNames: true,
        failures: [
          KeepFailure(
              ref: 'a',
              title: 'Nude',
              artist: 'Radiohead',
              reason: 'YouTube is resting.',
              retry: true),
          KeepFailure(
              ref: 'b',
              title: 'Weird Fishes',
              artist: 'Radiohead',
              reason: 'Not found.',
              retry: false),
        ]);

    expect(find.text('Stopped · 7 of 10 on this phone · 3 songs did not come'),
        findsOneWidget);
    expect(find.text('Resume'), findsOneWidget);
    expect(find.text('Stop'), findsNothing);
    expect(find.text('Retry'), findsNothing);
    expect(find.text('Nude: YouTube is resting.'), findsOneWidget,
        reason: 'the songs that did not come are still named under the line');
    expect(find.bySemanticsLabel('Resume the download'), findsOneWidget);

    await tester.tap(find.text('Resume'));
    await tester.pump();
    expect(calls.resumed, [target]);
    expect(calls.stopped, isEmpty);
  });

  testWidgets(
      'N-39: the bar of a stopped download is grey, not the accent and not amber; "Stopping…" dims the bar and has no button',
      (tester) async {
    await show(tester, line: stoppedLine);
    var bar = tester.widget<DownloadBar>(find.byType(DownloadBar));
    expect(bar.stopped, isTrue);
    expect(bar.dimmed, isFalse);
    expect(bar.phoneFraction, closeTo(12 / 217, 1e-9));

    await show(tester, line: coming.asStopping());
    expect(find.text('Stopping…'), findsOneWidget);
    expect(find.text('Stop'), findsNothing);
    expect(find.text('Resume'), findsNothing);
    expect(find.text('Retry'), findsNothing);
    bar = tester.widget<DownloadBar>(find.byType(DownloadBar));
    expect(bar.dimmed, isTrue);
    expect(bar.phoneFraction, closeTo(12 / 217, 1e-9),
        reason: 'the bar stays where it was');
  });

  testWidgets(
      'N-39: Stop and Retry can stand together while songs are coming and some did not come, and at 200 percent text nothing overflows',
      (tester) async {
    await show(tester,
        textScale: 2,
        line: const DownloadLine(
            '12 of 217 on this phone · 40 ready on your server',
            phoneFraction: 0.05,
            failed: 2,
            canRetry: true,
            twoStages: true,
            canStop: true));

    expect(find.text('Stop'), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
