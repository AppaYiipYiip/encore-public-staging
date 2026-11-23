import 'package:encore/app/notifications.dart';
import 'package:encore/domain/download_card.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_test/flutter_test.dart';

/// docs/design S-95 (P2-29): what the card asks of Android. The REAL plugin runs here, on Android's terms, and only its platform channel is a
/// recorder, so these are the exact words Android would receive: the channel, the importance, the time to live, the bar.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('dexterous.com/flutter/local_notifications');
  final calls = <MethodCall>[];

  late LocalNotifications notifications;

  setUp(() {
    calls.clear();
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    FlutterLocalNotificationsPlatform.instance =
        AndroidFlutterLocalNotificationsPlugin();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      return call.method == 'initialize' ? true : null;
    });
    notifications = LocalNotifications(FlutterLocalNotificationsPlugin());
  });

  tearDown(() {
    debugDefaultTargetPlatformOverride = null;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  Map<Object?, Object?> shown(int index) {
    final shows = [
      for (final c in calls)
        if (c.method == 'show') c
    ];
    return shows[index].arguments as Map<Object?, Object?>;
  }

  Map<Object?, Object?> details(int index) =>
      shown(index)['platformSpecifics']! as Map<Object?, Object?>;

  const live = CardSpec(
    title: 'Downloading Prog snob',
    body: '12 of 217 on this phone · 40 ready on your server',
    progress: 0.12,
  );

  test('the live card is silent, low, on its own channel, and times out',
      () async {
    await notifications.post(const CardPost(
      id: kRunningCardId,
      kind: CardKind.running,
      spec: live,
      timeoutAfter: Duration(minutes: 3),
    ));

    expect(shown(0)['id'], kRunningCardId);
    expect(shown(0)['title'], 'Downloading Prog snob');
    expect(shown(0)['payload'], kDownloadsRoute);
    final d = details(0);
    expect(d['channelId'], kDownloadsChannelId);
    expect(d['channelId'], isNot(kNewMusicChannelId),
        reason:
            'muting the news must not mute the downloads, and the other way round');
    expect(d['importance'], Importance.low.value);
    expect(d['silent'], isTrue);
    expect(d['playSound'], isFalse);
    expect(d['enableVibration'], isFalse);
    expect(d['onlyAlertOnce'], isTrue);
    expect(d['ongoing'], isFalse,
        reason:
            'a frozen card the person could not swipe away is worse than none');
    expect(d['timeoutAfter'], const Duration(minutes: 3).inMilliseconds);
    expect(d['showProgress'], isTrue);
    expect(d['progress'], 120);
    expect(d['maxProgress'], 1000);
    expect(d['indeterminate'], isFalse);
  });

  test('a card that has just started has a bar with no end yet', () async {
    await notifications.post(const CardPost(
      id: kRunningCardId,
      kind: CardKind.running,
      spec: CardSpec(title: 'Downloading Prog snob', body: 'Starting…'),
      timeoutAfter: Duration(minutes: 3),
    ));

    expect(details(0)['showProgress'], isTrue);
    expect(details(0)['indeterminate'], isTrue);
  });

  test('the dated card has no bar and no time to live', () async {
    await notifications.post(const CardPost(
      id: kRunningCardId,
      kind: CardKind.running,
      spec: CardSpec(
        title: 'Prog snob is still saving on your server',
        body:
            '150 of 214 were ready at 9:03. Open Encore to see how far it is now.',
        dated: true,
      ),
    ));

    final d = details(0);
    expect(d['timeoutAfter'], isNull);
    expect(d['showProgress'], isFalse);
    expect(d['indeterminate'], isFalse);
    expect(d['silent'], isTrue);
  });

  test('a card of a job that is over is swiped away by the person, quietly',
      () async {
    await notifications.post(CardPost(
      id: resultCardId('playlist:p1'),
      kind: CardKind.result,
      spec: const CardSpec(
          title: 'Prog snob is ready offline',
          body: '217 songs are on this phone.'),
    ));

    final d = details(0);
    expect(d['autoCancel'], isTrue);
    expect(d['timeoutAfter'], isNull);
    expect(d['showProgress'], isFalse);
    expect(d['silent'], isTrue);
    expect(d['importance'], Importance.low.value);
  });

  test(
      "N-39: no card has a button, not even the card of a Download that was stopped: a card outside the app cannot act, Resume stands in Downloaded",
      () async {
    await notifications.post(const CardPost(
      id: kRunningCardId,
      kind: CardKind.running,
      spec: live,
      timeoutAfter: Duration(minutes: 3),
    ));
    await notifications.post(CardPost(
      id: resultCardId('pin:playlist:p1'),
      kind: CardKind.result,
      spec: const CardSpec(
          title: 'Prog snob is stopped',
          body: '12 of 217 stay on this phone. Resume continues from there.'),
    ));

    for (final i in [0, 1]) {
      expect(details(i)['actions'], anyOf(isNull, isEmpty),
          reason: 'card $i has an action button');
    }
    final stopped = details(1);
    expect(stopped['autoCancel'], isTrue);
    expect(stopped['silent'], isTrue);
    expect(stopped['timeoutAfter'], isNull);
    expect(stopped['showProgress'], isFalse);
    expect(stopped['channelId'], kDownloadsChannelId);
  });

  test('the same id replaces the card in place', () async {
    await notifications.post(
        const CardPost(id: kRunningCardId, kind: CardKind.running, spec: live));
    await notifications.post(const CardPost(
        id: kRunningCardId,
        kind: CardKind.running,
        spec: CardSpec(
            title: 'Prog snob', body: 'x', progress: 0.5, dated: true)));

    expect(shown(0)['id'], shown(1)['id']);
  });

  test('cancelling takes the card by its id', () async {
    await notifications.cancel(kRunningCardId);

    final cancel = calls.singleWhere((c) => c.method == 'cancel');
    expect((cancel.arguments as Map<Object?, Object?>)['id'], kRunningCardId);
  });

  test('several downloads pulled open show a line each', () async {
    await notifications.post(const CardPost(
      id: kRunningCardId,
      kind: CardKind.running,
      spec: CardSpec(
        title: '2 downloads',
        body: '45 of 226 songs on this phone',
        expanded: 'Prog snob\n12 of 217 on this phone\nFairouz\n3 of 9',
      ),
    ));

    final style = details(0)['styleInformation']! as Map<Object?, Object?>;
    expect(style['bigText'], contains('Fairouz'));
  });
}
