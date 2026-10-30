import 'package:encore/features/news/news_time.dart';
import 'package:flutter_test/flutter_test.dart';

/// How long ago a piece of news was, in the words of the drawing (S-24): "10 min", "Today", "Yesterday", "Monday".
void main() {
  // Sunday 25 October 2026, 10:30.
  final now = DateTime(2026, 10, 25, 10, 30);

  String label(DateTime at) => newsTimeLabel(now, at);

  test('the first hour is counted in minutes', () {
    expect(label(now), 'Now');
    expect(label(now.subtract(const Duration(seconds: 50))), 'Now');
    expect(label(now.subtract(const Duration(minutes: 1))), '1 min');
    expect(label(now.subtract(const Duration(minutes: 10))), '10 min');
    expect(label(now.subtract(const Duration(minutes: 59))), '59 min');
  });

  test('later the same day is "Today", and the day before "Yesterday"', () {
    expect(label(DateTime(2026, 10, 25, 9, 0)), 'Today');
    expect(label(DateTime(2026, 10, 25, 0, 5)), 'Today');
    expect(label(DateTime(2026, 10, 24, 23, 59)), 'Yesterday');
    expect(label(DateTime(2026, 10, 24, 1, 0)), 'Yesterday');
  });

  test('within the week it is the day of the week, then the date', () {
    expect(label(DateTime(2026, 10, 23, 12)), 'Friday');
    expect(label(DateTime(2026, 10, 19, 12)), 'Monday');
    expect(label(DateTime(2026, 10, 18, 12)), '18 Oct',
        reason: 'a week ago: the date, not a day that could mean next Sunday');
    expect(label(DateTime(2026, 3, 2, 12)), '2 Mar');
    expect(label(DateTime(2025, 12, 31, 12)), '31 Dec 2025');
  });

  test('a time in the future (a clock that is a little off) is "Now"', () {
    expect(label(now.add(const Duration(minutes: 3))), 'Now');
  });
}
