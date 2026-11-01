import 'dart:async';

import 'package:drift/drift.dart' show Value;
import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/people/people_client.dart';
import 'package:encore/features/common/download_button.dart';
import 'package:encore/features/common/widgets.dart';
import 'package:encore/features/people/people_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/device_profile.dart';
import '../support/fake_people_api.dart';
import '../support/test_app.dart';

/// The owner (2026-10-31): "sometimes buttons are hidden or clickable elements are hidden under the three navigation buttons, it happened
/// before". `device_profiles_test.dart` covers the main screens and the older sheets. This file covers what the phone batch of 2026-10-31
/// added or changed: Your server and its addresses, Library & sync, Downloads, the menu of a Library row, the song menu in each of its
/// download states, the sheet that takes a download off, and the invitation dialog (with its QR). Nothing tappable may lie under the bar.
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

  const owner = PeopleMe(
      user: 'owner', isAdmin: true, sharing: false, role: PersonRole.owner);

  for (final profile in DeviceProfile.all) {
    group(profile.name, () {
      for (final entry in const {
        'Your server': '/settings/server',
        'Library & sync': '/settings/sync',
        'Downloads & storage': '/settings/downloads',
        'Downloaded (Library)': '/library',
      }.entries) {
        testWidgets('${entry.key}: nothing tappable is under the system bar',
            (tester) async {
          final semantics = tester.ensureSemantics();
          applyProfile(tester, profile);
          final app = await pumpApp(tester, size: profile.size);
          await open(tester, entry.value);

          await expectReachable(tester, profile, entry.key);
          await closeApp(tester, app.db);
          semantics.dispose();
        });
      }

      testWidgets('the menu of a Library row (the three dots)', (tester) async {
        final semantics = tester.ensureSemantics();
        applyProfile(tester, profile);
        final app = await pumpApp(tester, size: profile.size);
        await open(tester, '/library');

        // On a small phone with big text the row starts below the fold.
        final dots = find.byTooltip('More options for Late night');
        await tester.scrollUntilVisible(dots, 200,
            scrollable: find.byType(Scrollable).first);
        await tester.tap(dots);
        await settle(tester);
        await expectReachable(tester, profile, 'the menu of a Library row');
        await closeApp(tester, app.db);
        semantics.dispose();
      });

      for (final state in const [
        'not downloaded',
        'own download',
        'with its playlist'
      ]) {
        testWidgets('the song menu, $state', (tester) async {
          final semantics = tester.ensureSemantics();
          applyProfile(tester, profile);
          final app = await pumpApp(tester, size: profile.size);
          if (state == 'own download') {
            await pin(app.db, app.serverId, 'track', 'al1-t1');
            await onPhone(app.db, app.serverId, 'al1-t1');
          } else if (state == 'with its playlist') {
            await pin(app.db, app.serverId, 'playlist', 'pl2');
            await onPhone(app.db, app.serverId, 'al1-t1');
          }
          await open(tester, '/home/album/al1');

          // On a small phone with big text the first song is not even built until the header is scrolled away.
          for (var i = 0;
              i < 6 && find.byType(TrackTile).evaluate().isEmpty;
              i++) {
            await tester.drag(
                find.byType(Scrollable).first, const Offset(0, -300));
            await tester.pump(const Duration(milliseconds: 200));
          }
          final song = find.byType(TrackTile).first;
          await tester.ensureVisible(song);
          await tester.longPress(song);
          await settle(tester);
          await expectReachable(tester, profile, 'the song menu, $state');
          await closeApp(tester, app.db);
          semantics.dispose();
        });
      }

      testWidgets('the sheet that takes a playlist download off',
          (tester) async {
        final semantics = tester.ensureSemantics();
        applyProfile(tester, profile);
        final app = await pumpApp(tester, size: profile.size);
        await pin(app.db, app.serverId, 'playlist', 'pl2');
        await open(tester, '/home/playlist/pl2');

        // The pin state arrives a moment after the page: a tap before that would pin again instead of asking.
        await tester.pump(const Duration(milliseconds: 800));
        await settle(tester);
        await tester.tap(find.byType(DownloadButton));
        await settle(tester);
        expect(find.text('Keep downloaded'), findsOneWidget,
            reason: 'the sheet is open');
        await expectReachable(tester, profile, 'the remove-download sheet');
        await tester.tap(find.text('Keep downloaded'));
        await settle(tester);
        await closeApp(tester, app.db);
        semantics.dispose();
      });

      testWidgets('the invitation dialog with its link and its QR',
          (tester) async {
        final semantics = tester.ensureSemantics();
        applyProfile(tester, profile);
        final api = FakePeopleApi(me_: owner)
          ..createAnswer = Result.ok(CreatedInvite(
            id: '1',
            url: 'http://192.168.50.133:4540/encore/join/ABCD-EFGH-JK1',
            expiresAt: DateTime(2026, 10, 24),
          ));
        final app = await pumpApp(tester, size: profile.size, overrides: [
          peopleApiProvider.overrideWith((ref) async => api),
        ]);
        final element = tester.element(find.byType(Scaffold).first);
        unawaited(GoRouter.of(element).push<void>('/settings/server'));
        await settle(tester);
        await tester.scrollUntilVisible(find.text('Invite someone'), 200,
            scrollable: find.byType(Scrollable).first);
        await settle(tester);
        await tester.tap(find.text('Invite someone'));
        await settle(tester);
        await tester.tap(find.text('Create invitation link'));
        await settle(tester);

        await expectReachable(tester, profile, 'the invitation dialog');
        await closeApp(tester, app.db);
        semantics.dispose();
      });
    });
  }
}
