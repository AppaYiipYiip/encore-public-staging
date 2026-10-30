import 'dart:async';
import 'dart:collection';

import '../../core/result.dart';

/// An address the Encore server signed, and the moment it stops working.
class SignedAddress {
  const SignedAddress(this.url, this.expiresAt);

  final Uri url;
  final DateTime expiresAt;
}

/// The signed address of every song, asked of the server once and kept until just before it runs out (docs/tasks P2-20 slice 2): a tap on a
/// song asked for before, the next song of a queue and a retry cost no round trip. The address is the same at every quality; the quality is
/// added to it by the caller.
class StreamAddresses {
  StreamAddresses({
    required Future<Result<SignedAddress>> Function(String refId) fetch,
    DateTime Function() clock = DateTime.now,
    this.margin = const Duration(minutes: 10),
    this.capacity = 300,
  })  : _fetch = fetch,
        _clock = clock;

  final Future<Result<SignedAddress>> Function(String refId) _fetch;
  final DateTime Function() _clock;

  /// An address is renewed this long before it ends, so a song never stops half way for want of a new one.
  final Duration margin;

  /// How many addresses are kept (the oldest asked-for goes first).
  final int capacity;

  final LinkedHashMap<String, SignedAddress> _known = LinkedHashMap();
  final Map<String, Future<Uri>> _asking = {};

  /// The address to play the song [refId] from. Throws the server's failure in words when it cannot be had.
  Future<Uri> forRef(String refId) {
    final known = _known[refId];
    if (known != null && known.expiresAt.isAfter(_clock().add(margin))) {
      return Future.value(known.url);
    }
    final already = _asking[refId];
    if (already != null) return already;
    // A block, not an arrow: `whenComplete` waits for a Future the callback returns, and `remove` would hand back this very one.
    final asked = _ask(refId).whenComplete(() {
      _asking.remove(refId);
    });
    _asking[refId] = asked;
    return asked;
  }

  Future<Uri> _ask(String refId) async {
    final got = (await _fetch(refId)).getOrThrow();
    _known.remove(refId);
    _known[refId] = got;
    while (_known.length > capacity) {
      _known.remove(_known.keys.first);
    }
    return got.url;
  }

  /// Forgets everything (another server, another person).
  void clear() => _known.clear();
}

/// The quality asked for, added to a signed address. The server checks these against the qualities it offers and ignores nothing: they are not
/// part of the signature, so one address serves every quality. "Original" adds nothing.
Uri withQuality(
  Uri address, {
  int? maxBitRate,
  String? format,
  bool estimateContentLength = false,
}) {
  final extras = {
    if (maxBitRate != null && maxBitRate > 0) 'maxBitRate': '$maxBitRate',
    if (format != null && format.isNotEmpty && format != 'raw')
      'format': format,
    if (estimateContentLength) 'estimateContentLength': 'true',
  };
  if (extras.isEmpty) return address;
  return address
      .replace(queryParameters: {...address.queryParameters, ...extras});
}

/// The ticket that opens every picture of the server for a while: one for the whole screen, not one address per cover.
class CoverPass {
  const CoverPass({
    required this.person,
    required this.expiresAt,
    required this.signature,
  });

  final String person;
  final DateTime expiresAt;
  final String signature;
}

/// Holds the [CoverPass] and writes the address of any picture with it. The address has no login in it; the ticket is renewed a day before it
/// ends (on the next start or return to the app), and the picture cache is keyed by picture and size, never by this address (ADR-017).
class CoverPassHolder {
  CoverPassHolder({
    required Future<Result<CoverPass>> Function() fetch,
    required Uri Function() baseUrl,
    DateTime Function() clock = DateTime.now,
    this.renewBefore = const Duration(days: 1),
  })  : _fetch = fetch,
        _baseUrl = baseUrl,
        _clock = clock;

  final Future<Result<CoverPass>> Function() _fetch;
  final Uri Function() _baseUrl;
  final DateTime Function() _clock;
  final Duration renewBefore;

  CoverPass? _pass;
  Future<void>? _asking;
  int _generation = 0;
  final StreamController<int> _changes = StreamController<int>.broadcast();

  /// How many tickets have arrived: pictures asked for before the first one were placeholders, and are asked for again when it changes.
  int get generation => _generation;

  Stream<int> get changes => _changes.stream;

  bool get _usable {
    final pass = _pass;
    return pass != null && pass.expiresAt.isAfter(_clock());
  }

  /// The address of the picture [coverId] at [size] pixels, or `null` while there is no usable ticket.
  Uri? urlFor(String coverId, int size) {
    final pass = _pass;
    if (pass == null || !_usable) return null;
    final base = _baseUrl();
    return base.replace(
      path:
          '${base.path.replaceAll(RegExp(r'/+$'), '')}/encore/cover/${Uri.encodeComponent(coverId)}',
      queryParameters: {
        'size': '$size',
        'p': pass.person,
        'e': '${pass.expiresAt.millisecondsSinceEpoch ~/ 1000}',
        'sig': pass.signature,
      },
    );
  }

  /// Gets a ticket when there is none, or it ends within [renewBefore]. Never throws: pictures simply stay as they were when the server
  /// does not answer, and the next call tries again.
  Future<void> ensure() {
    final pass = _pass;
    if (pass != null && pass.expiresAt.isAfter(_clock().add(renewBefore))) {
      return Future.value();
    }
    return _asking ??= _renew().whenComplete(() => _asking = null);
  }

  Future<void> _renew() async {
    final got = (await _fetch()).valueOrNull;
    if (got == null) return;
    _pass = got;
    _generation++;
    if (!_changes.isClosed) _changes.add(_generation);
  }

  /// The server refused a picture's address: forget the ticket, the next [ensure] gets a new one.
  void expire() => _pass = null;

  Future<void> dispose() => _changes.close();
}
