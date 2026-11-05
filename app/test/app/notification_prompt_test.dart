import 'package:encore/app/notifications.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Counting extends LocalNotifications {
  int asked = 0;

  /// What Android would say about notifications right now (below Android 13, or once granted: allowed).
  bool allowed = false;

  @override
  Future<bool> requestPermission() async {
    asked++;
    return true;
  }

  @override
  Future<bool> areAllowed() async => allowed;
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('the permission is requested once, at the first opportunity', () async {
    final n = _Counting();

    expect(await askForNotificationsOnce(n, anyAlertOn: true), isTrue);
    expect(await askForNotificationsOnce(n, anyAlertOn: true), isFalse);
    expect(n.asked, 1);
  });

  test('with every alert off nothing is asked, and it is not used up',
      () async {
    final n = _Counting();

    expect(await askForNotificationsOnce(n, anyAlertOn: false), isFalse);
    expect(n.asked, 0);
    // Turning an alert on later still gets its one question.
    expect(await askForNotificationsOnce(n, anyAlertOn: true), isTrue);
    expect(n.asked, 1);
  });

  group('askForDownloadNotificationsOnce (D-52: download progress, once)', () {
    test('at the first Download it explains, then asks Android, once',
        () async {
      final n = _Counting();
      var explained = 0;
      Future<bool> yes() async {
        explained++;
        return true;
      }

      expect(await askForDownloadNotificationsOnce(n, explain: yes), isTrue);
      expect(await askForDownloadNotificationsOnce(n, explain: yes), isFalse);
      expect(explained, 1);
      expect(n.asked, 1);
    });

    test('"Not now" sends no system prompt and is never asked again', () async {
      final n = _Counting();

      expect(
          await askForDownloadNotificationsOnce(n, explain: () async => false),
          isFalse);
      expect(
          await askForDownloadNotificationsOnce(n, explain: () async => true),
          isFalse);
      expect(n.asked, 0);
    });

    test('nothing is asked, or explained, when notifications already work',
        () async {
      final n = _Counting()..allowed = true;
      var explained = 0;

      final asked = await askForDownloadNotificationsOnce(n, explain: () async {
        explained++;
        return true;
      });

      expect(asked, isFalse);
      expect(explained, 0);
      expect(n.asked, 0);
    });

    test('it does not use up, and is not used up by, the news-alert question',
        () async {
      final n = _Counting();

      expect(await askForNotificationsOnce(n, anyAlertOn: true), isTrue);
      expect(
          await askForDownloadNotificationsOnce(n, explain: () async => true),
          isTrue);
      expect(n.asked, 2);
    });
  });
}
