import 'dart:async';

import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/features/common/download_button.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// Owner, 7 Nov 2026, on his phone: "pressing the download button ... waits a second, then the download starts". The pin and the first look at the
/// songs take a moment (a playlist of 2,000 songs more than a small one); a press must show what it did at once.
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets(
      'a press shows "downloading" at once, before the pin has answered, and the button goes back to what the pin says when it has',
      (tester) async {
    final actions = _SlowActions();
    await tester.pumpWidget(ProviderScope(
      overrides: [downloadActionsProvider.overrideWithValue(actions)],
      child: MaterialApp(
        theme:
            buildEncoreTheme(EncoreColors.dark(), brightness: Brightness.dark),
        home: const Scaffold(
          body: Center(
            child: DownloadButton(
              type: PinTargetType.playlist,
              targetId: 'pl_1',
              name: 'Favorite Songs',
            ),
          ),
        ),
      ),
    ));
    await tester.pump();
    expect(find.bySemanticsLabel('Download Favorite Songs'), findsOneWidget);

    await tester.tap(find.byType(DownloadButton));
    await tester.pump(); // one frame: the pin is still waiting

    expect(actions.asked, ['playlist:pl_1']);
    expect(find.bySemanticsLabel('Download Favorite Songs'), findsNothing,
        reason: 'the button no longer says "Download"');
    expect(find.byType(CircularProgressIndicator), findsOneWidget,
        reason: 'the ring of a download that is starting is there');

    actions.finish.complete();
    await tester.pumpAndSettle();

    // the fake pin wrote nothing, so the pins say "off" again: the press is over
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });
}

class _SlowActions implements DownloadActions {
  final List<String> asked = [];
  final Completer<void> finish = Completer<void>();

  @override
  Future<void> pin(PinTargetType type, String targetId,
      {AudioQuality? quality}) async {
    asked.add('${type.name}:$targetId');
    await finish.future;
  }

  @override
  Future<void> unpin(PinTargetType type, String targetId) async {}

  @override
  Future<void> retry() async {}

  @override
  Future<void> removeAll() async {}
}
