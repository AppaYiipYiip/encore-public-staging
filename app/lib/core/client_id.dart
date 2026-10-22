import 'dart:math';

/// Ids the phone makes itself for what it creates (docs/17 section 1): a playlist (`pl_...`), an entry in one (`pe_...`), an import (`im_...`).
///
/// Making them here, before the server has heard of the thing, is what lets an offline create be retried without ever making it twice: the
/// same id arrives, the server says "already there". The shape is the server's own: a prefix and 26 characters of Crockford base32, the first
/// ten the time (so ids sort by creation) and sixteen random.
const String _alphabet = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

final Random _random = Random.secure();

String _encode(int value, int length) {
  final out = List<String>.filled(length, '0');
  var v = value;
  for (var i = length - 1; i >= 0; i--) {
    out[i] = _alphabet[v & 31];
    v >>= 5;
  }
  return out.join();
}

/// `pl_01M5H...` for [prefix] `pl`. [atMs] is for tests (and for an id that should sort with an event that happened earlier).
String newClientId(String prefix, {int? atMs}) {
  final stamp = atMs ?? DateTime.now().millisecondsSinceEpoch;
  final randomPart = StringBuffer();
  for (var i = 0; i < 16; i++) {
    randomPart.write(_alphabet[_random.nextInt(32)]);
  }
  return '${prefix}_${_encode(stamp, 10)}$randomPart';
}

/// Whether [value] is a well-formed id with that [prefix].
bool isClientId(Object? value, String prefix) =>
    value is String &&
    RegExp('^${RegExp.escape(prefix)}_[0-9A-HJKMNP-TV-Z]{26}\$')
        .hasMatch(value);
