import 'package:encore/domain/eq_presets.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('flat is flat on any layout', () {
    expect(
        EqPreset.flat.forBands([60, 230, 910, 3600, 14000]), everyElement(0));
    expect(
        EqPreset.flat.forBands([31, 62, 125, 250, 500, 1000]), everyElement(0));
  });

  test('reference band centres reproduce the preset exactly', () {
    const p = EqPreset('t', 'T', [6, 4, 0, -2, 3]);
    expect(p.forBands(EqPreset.referenceHz), [6, 4, 0, -2, 3]);
  });

  test('in-between bands interpolate on a log-frequency axis', () {
    const p = EqPreset('t', 'T', [0, 8, 8, 8, 8]);
    // Geometric middle of 60 and 230 Hz is ~117 Hz: halfway in log space.
    final mid = p.forBands([117.48])[0];
    expect(mid, closeTo(4, 0.05));
  });

  test('values outside the reference range clamp to the end points', () {
    const p = EqPreset('t', 'T', [5, 0, 0, 0, -5]);
    final g = p.forBands([20, 20000]);
    expect(g[0], 5);
    expect(g[1], -5);
  });

  test('device limits clamp the result', () {
    const p = EqPreset('t', 'T', [12, 0, 0, 0, 0]);
    expect(p.forBands([60], min: -6, max: 6).single, 6);
  });

  test('preset ids are unique and lookup works', () {
    final ids = EqPreset.all.map((e) => e.id).toSet();
    expect(ids.length, EqPreset.all.length);
    expect(EqPreset.byId('metal')!.label, 'Metal');
    expect(EqPreset.byId('nope'), isNull);
  });

  test('frequency labels', () {
    expect(formatHz(60), '60 Hz');
    expect(formatHz(3600), '3.6 kHz');
    expect(formatHz(14000), '14 kHz');
    expect(formatHz(1000), '1 kHz');
  });
}
