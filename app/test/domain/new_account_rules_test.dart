import 'package:encore/domain/new_account_rules.dart';
import 'package:flutter_test/flutter_test.dart';

/// What a person who joins by invitation may choose, checked on the phone
/// before anything is sent. The server has the same rules (and the final say);
/// its sentences are used word for word so a person reads one voice.
void main() {
  group('a username', () {
    test('is accepted when it is lower case letters, digits, dots, dashes', () {
      for (final name in ['mia', 'dj.mia-9', 'a_b', 'abc', 'x' * 32]) {
        expect(checkNewUsername(name), isNull, reason: name);
      }
    });

    test('is refused when it is too short, too long or starts with a digit',
        () {
      for (final name in ['', 'mi', 'x' * 33, '9lives', '.dot', '-dash']) {
        expect(checkNewUsername(name), contains('3 to 32 characters'),
            reason: name);
      }
    });

    test('with capitals or spaces is refused, the phone offers lower case', () {
      expect(checkNewUsername('Mia'), contains('lower case'));
      expect(checkNewUsername('mia and co'), contains('lower case'));
      expect(suggestUsername('  Mia '), 'mia',
          reason: 'what people type first is a capital');
    });

    test('that would look like something it is not is not available', () {
      for (final name in ['admin', 'owner', 'root', 'guest', 'encore']) {
        expect(
            checkNewUsername(name),
            'That name is not available. Choose '
            'another.',
            reason: name);
      }
    });
  });

  group('a password', () {
    test('needs at least 8 characters', () {
      expect(checkNewPassword('1234567'),
          'Choose a password of at least 8 characters.');
      expect(checkNewPassword('12345678'), isNull);
      expect(checkNewPassword('a long sentence works too'), isNull);
    });

    test('has a limit that nobody reaches by accident', () {
      expect(checkNewPassword('x' * 200), isNull);
      expect(checkNewPassword('x' * 201), isNotNull);
    });
  });
}
