/// Injectable time source so sync/scheduling logic is testable without
/// real time (docs/05-testing-and-quality.md rule 2).
abstract interface class Clock {
  DateTime now();
}

/// Wall-clock implementation.
class SystemClock implements Clock {
  const SystemClock();

  @override
  DateTime now() => DateTime.now();
}

/// Manually advanced clock for tests.
class FakeClock implements Clock {
  FakeClock([DateTime? start]) : _now = start ?? DateTime.utc(2026, 1, 1);

  DateTime _now;

  @override
  DateTime now() => _now;

  void advance(Duration by) => _now = _now.add(by);

  void set(DateTime value) => _now = value;
}
