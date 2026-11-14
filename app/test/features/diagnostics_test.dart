import 'package:encore/app/server_kind.dart';
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

  group('F53: which kind of server the session is talking to', () {
    test('an Encore server is said so', () {
      expect(describeSessionMode(signedIn: true, kind: ServerKind.encore),
          'Encore server');
    });

    test(
        'a plain music server that is still being looked at says it is still looking',
        () {
      expect(describeSessionMode(signedIn: true, kind: ServerKind.detecting),
          'plain music server, still looking for an Encore server');
    });

    test('a plain music server that answered as one is only plain', () {
      expect(describeSessionMode(signedIn: true, kind: ServerKind.plain),
          'plain music server');
    });

    test('nobody signed in has no session to describe', () {
      expect(describeSessionMode(signedIn: false, kind: ServerKind.plain),
          'none (nobody is signed in, or it is still starting)');
    });
  });

  test('an empty log still yields a valid report', () {
    final text = buildDiagnosticsReport(sections: {}, log: []);
    expect(text.trim(), '== Recent log ==');
  });
}
