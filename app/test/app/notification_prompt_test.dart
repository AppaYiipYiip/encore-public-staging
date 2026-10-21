import 'package:encore/app/notifications.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Counting extends LocalNotifications {
  int asked = 0;

  @override
  Future<bool> requestPermission() async {
    asked++;
    return true;
  }
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
}
