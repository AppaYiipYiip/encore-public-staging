import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/domain/download_line.dart';
import 'package:encore/features/downloads/download_line_providers.dart';
import 'package:encore/features/downloads/download_status.dart';
import 'package:encore/features/downloads/keep_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// The line under a download's title with its two-tone bar, the songs that did not come and Retry (docs/design S-16, S-17; P2-22 parts 2 and 4).
void main() {
  setUpAll(loadAppFonts);

  const target = DownloadTarget.pin(PinTargetType.playlist, 'pl_1');

  KeepFailure failure(String title, String reason, {bool retry = true}) =>
      KeepFailure(
          ref: 'sr_$title',
          title: title,
          artist: 'Artist',
          reason: reason,
          retry: retry);

  Future<List<DownloadTarget>> show(
    WidgetTester tester, {
    DownloadLine? line,
    List<KeepFailure> failures = const [],
    bool showNames = false,
    double textScale = 1,
  }) async {
    final retried = <DownloadTarget>[];
    final overrides = <Override>[
      downloadLineProvider.overrideWith((ref, t) => line),
      keepFailuresProvider.overrideWith((ref, t) => failures),
      retryDownloadProvider.overrideWithValue((t) async => retried.add(t)),
    ];
    await tester.pumpWidget(ProviderScope(
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
    return retried;
  }

  const twoStages = DownloadLine(
    '12 of 217 on this phone · 40 ready on your server',
    phoneFraction: 12 / 217,
    serverFraction: 40 / 217,
    twoStages: true,
  );

  testWidgets('the line and a bar of two tones', (tester) async {
    await show(tester, line: twoStages);

    expect(find.text('12 of 217 on this phone · 40 ready on your server'),
        findsOneWidget);
    final bar = tester.widget<DownloadBar>(find.byType(DownloadBar));
    expect(bar.phoneFraction, closeTo(12 / 217, 1e-9));
    expect(bar.serverFraction, closeTo(40 / 217, 1e-9));
  });

  testWidgets(
      'nothing for a download that is not made, finished, or a plain server\'s',
      (tester) async {
    await show(tester, line: null);
    expect(find.byType(DownloadBar), findsNothing);
    expect(find.byType(Text), findsNothing);

    await show(tester,
        line: const DownloadLine('Downloaded • 9 songs',
            phoneFraction: 1, complete: true, twoStages: true));
    expect(find.byType(DownloadBar), findsNothing);

    await show(tester, line: const DownloadLine('Downloading 4 of 10'));
    expect(find.byType(DownloadBar), findsNothing,
        reason:
            'the line a plain music server has always had keeps its place and its look');
  });

  testWidgets(
      'Retry is offered when asking again can help, and does what it says',
      (tester) async {
    final retried = await show(tester,
        line: const DownloadLine('3 songs did not come',
            failed: 3, canRetry: true, twoStages: true));

    await tester.tap(find.text('Retry'));
    await tester.pump();

    expect(retried, [target]);
  });

  testWidgets('no Retry for songs nobody can get', (tester) async {
    await show(tester,
        line: const DownloadLine('2 songs did not come',
            failed: 2, canRetry: false, twoStages: true));

    expect(find.text('Retry'), findsNothing);
    expect(find.text('2 songs did not come'), findsOneWidget);
  });

  testWidgets(
      'the songs that did not come are named with their reason, three at most',
      (tester) async {
    await show(
      tester,
      showNames: true,
      line: const DownloadLine('5 songs did not come',
          failed: 5, canRetry: true, twoStages: true),
      failures: [
        failure('Nude', 'YouTube is resting.'),
        failure('Reckoner', 'YouTube is resting.'),
        failure('Weird Fishes', 'Not found.', retry: false),
        failure('Airbag', 'Not found.', retry: false),
        failure('Lucky', 'Not found.', retry: false),
      ],
    );

    expect(find.text('Nude: YouTube is resting.'), findsOneWidget);
    expect(find.text('Weird Fishes: Not found.'), findsOneWidget);
    expect(find.text('Airbag: Not found.'), findsNothing);
    expect(find.text('and 2 more'), findsOneWidget);
  });

  testWidgets('no names and no Retry while the phone waits for a connection',
      (tester) async {
    await show(
      tester,
      showNames: true,
      line: const DownloadLine(
          '3 of 6 on this phone · waiting for a connection',
          twoStages: true),
      failures: [failure('Nude', 'YouTube is resting.')],
    );

    expect(find.text('Nude: YouTube is resting.'), findsNothing);
    expect(find.text('Retry'), findsNothing);
  });

  testWidgets('without names a header stays to its line', (tester) async {
    await show(
      tester,
      line: const DownloadLine('1 song did not come',
          failed: 1, canRetry: true, twoStages: true),
      failures: [failure('Nude', 'YouTube is resting.')],
    );

    expect(find.text('Nude: YouTube is resting.'), findsNothing);
  });

  testWidgets(
      'Retry never stands alone: while songs are still coming, the failures are told on their own line (the owner could not tell why Retry was there)',
      (tester) async {
    await show(
      tester,
      line: const DownloadLine(
          '379 of 684 on this phone · 385 ready on your server',
          phoneFraction: 0.55,
          serverFraction: 0.56,
          failed: 12,
          canRetry: true,
          twoStages: true),
    );

    expect(find.text('12 songs did not come'), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
  });

  testWidgets(
      'one failed song is told as "1 song", and the line is not said twice',
      (tester) async {
    await show(
      tester,
      line: const DownloadLine('4 of 10 on this phone · 5 ready on your server',
          failed: 1, canRetry: true, twoStages: true),
    );
    expect(find.text('1 song did not come'), findsOneWidget);

    await show(
      tester,
      line: const DownloadLine('1 song did not come',
          failed: 1, canRetry: true, twoStages: true),
    );
    expect(find.text('1 song did not come'), findsOneWidget,
        reason: 'a line that already says it is not repeated');
  });

  testWidgets('Retry has a name for a screen reader', (tester) async {
    await show(tester,
        line: const DownloadLine('3 songs did not come',
            failed: 3, canRetry: true, twoStages: true));

    expect(find.bySemanticsLabel('Retry the songs that did not come'),
        findsOneWidget);
  });

  testWidgets('at double text size nothing overflows', (tester) async {
    await show(
      tester,
      textScale: 2,
      showNames: true,
      line: const DownloadLine(
          '12 of 217 on this phone · your server is resting until 21:40',
          failed: 4,
          canRetry: true,
          twoStages: true),
      failures: [
        failure('A very long song title that goes on and on',
            'YouTube is resting.'),
        failure('Another one', 'Not found.', retry: false),
      ],
    );

    expect(tester.takeException(), isNull);
  });

  group('what did not come, from both sides', () {
    test(
        'songs from the server and from the phone are named together, the phone ones in plain words',
        () {
      final container = ProviderContainer(overrides: [
        keepProvider.overrideWith(() => _FixedKeep(KeepState(
              supported: true,
              answered: true,
              groups: {
                const KeepGroupKey('playlist', 'pl_1'): KeepGroup(
                  kind: 'playlist',
                  id: 'pl_1',
                  total: 4,
                  ready: 3,
                  keeping: 0,
                  queued: 0,
                  failed: 1,
                  retryable: 1,
                  failures: [failure('Nude', 'YouTube is resting.')],
                ),
              },
            ))),
        phoneFailuresProvider.overrideWith((ref, t) => Stream.value(const [
              FailedSong(
                  ref: 'sr_air',
                  title: 'Airbag',
                  artist: 'Radiohead',
                  error:
                      'FileSystemException: No space left on device, path = /data/user/0/x'),
            ])),
      ]);
      addTearDown(container.dispose);
      container.listen(phoneFailuresProvider(target), (_, __) {});

      return Future<void>.delayed(const Duration(milliseconds: 20), () {
        final names = container.read(keepFailuresProvider(target));

        expect(names.map((f) => '${f.title}: ${f.reason}'), [
          'Nude: YouTube is resting.',
          'Airbag: There is no room on this phone.',
        ]);
        expect(names.map((f) => f.reason).join(' '), isNot(contains('/data/')));
      });
    });
  });
}

class _FixedKeep extends KeepController {
  _FixedKeep(this.initial);

  final KeepState initial;

  @override
  KeepState build() => initial;
}
