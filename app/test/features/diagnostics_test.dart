import 'package:encore/features/settings/diagnostics_screen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('report has titled sections, then the log', () {
    final text = buildDiagnosticsReport(
      sections: {
        'App': 'Encore 0.1.0 (profile)',
        'Server': 'tracks: 5049',
      },
      log: ['line one', 'line two'],
    );
    expect(text, contains('== App =='));
    expect(text, contains('Encore 0.1.0 (profile)'));
    expect(
        text.indexOf('== Server =='), greaterThan(text.indexOf('== App ==')));
    expect(text.indexOf('== Recent log =='),
        greaterThan(text.indexOf('== Server ==')));
    expect(text, endsWith('line two\n'));
  });

  test('an empty log still yields a valid report', () {
    final text = buildDiagnosticsReport(sections: {}, log: []);
    expect(text.trim(), '== Recent log ==');
  });
}
