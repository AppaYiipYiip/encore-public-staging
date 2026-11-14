import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/features/instant/song_refusals.dart';
import 'package:flutter_test/flutter_test.dart';

/// B-128: what the player does when a stream fails and it asks the server why. A song the server refuses **for good** (`song_unavailable`, not
/// retryable) is also told to the marks, whose lists then ask the server again at once; a failure that may pass (YouTube resting) is not.
void main() {
  final address = Uri.parse('http://home.test:4540/encore/stream/sr_1?sig=x');

  EncoreApi answering(int status, String body) => EncoreApi(
        dio: Dio()..httpClientAdapter = _Canned(status, body),
        baseUrl: () => Uri.parse('http://home.test:4540'),
        auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
      );

  const gone =
      '{"error":{"code":"song_unavailable","message":"Nothing matching that song was found.",'
      '"retryable":false,"retryAfterMs":null,"details":{"reason":"not_found"}}}';
  const resting =
      '{"error":{"code":"source_busy","message":"YouTube is resting.",'
      '"retryable":true,"retryAfterMs":60000,"details":{}}}';

  test(
      'a refusal for good is told to the marks once, and still answers the player',
      () async {
    var told = 0;

    final why = await askSongRefusal(answering(404, gone), address,
        onRefusedForGood: () => told++);

    expect(why!.permanent, isTrue);
    expect(why.message, 'Nothing matching that song was found.');
    expect(told, 1);
  });

  test('a refusal that may pass is not told to the marks', () async {
    var told = 0;

    final why = await askSongRefusal(answering(503, resting), address,
        onRefusedForGood: () => told++);

    expect(why!.permanent, isFalse);
    expect(told, 0);
  });

  test(
      'a stream that answers, and a server that is not an Encore server, say nothing',
      () async {
    var told = 0;

    expect(
        await askSongRefusal(answering(206, 'x'), address,
            onRefusedForGood: () => told++),
        isNull);
    expect(await askSongRefusal(null, address, onRefusedForGood: () => told++),
        isNull);
    expect(told, 0);
  });
}

class _Canned implements HttpClientAdapter {
  _Canned(this.status, this.body);

  final int status;
  final String body;

  @override
  Future<ResponseBody> fetch(RequestOptions options,
          Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async =>
      ResponseBody.fromString(body, status, headers: {
        Headers.contentTypeHeader: ['application/json'],
      });

  @override
  void close({bool force = false}) {}
}
