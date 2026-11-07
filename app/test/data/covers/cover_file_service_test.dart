import 'package:encore/data/covers/cover_file_service.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Measured on the dev server 2026-10-22: for an album it has no art for, the music server's `getCoverArt` answers 200 with a blank record
/// (a webp) and `Cache-Control: no-store`; real art is `public, max-age=31536000, immutable`. The blank record used to be cached for a year.
void main() {
  CoverFileService serviceAnswering(Map<String, String> headers) =>
      CoverFileService(
          client:
              MockClient.streaming((request, _) async => http.StreamedResponse(
                    Stream.value(const [1, 2, 3]),
                    200,
                    headers: headers,
                  )));

  test('real art is passed on to the cache', () async {
    final service = serviceAnswering(const {
      'cache-control': 'public, max-age=31536000, immutable',
      'content-type': 'image/jpeg',
    });

    final response =
        await service.get('http://music.test/rest/getCoverArt?id=al-1');

    expect(response.statusCode, 200);
    expect(await response.content.expand((b) => b).toList(), [1, 2, 3]);
  });

  test(
      'the blank record the music server makes up is refused, so nothing is stored',
      () async {
    final service = serviceAnswering(const {
      'cache-control': 'no-store',
      'content-type': 'image/webp',
    });

    await expectLater(
      service.get('http://music.test/rest/getCoverArt?id=al-1'),
      throwsA(isA<HttpExceptionWithStatus>()
          .having((e) => e.statusCode, 'status', 404)),
    );
  });

  test(
      'a refused address (401) is told to whoever holds the ticket, and still fails',
      () async {
    final refused = <Uri>[];
    final service = CoverFileService(
        client:
            MockClient.streaming((request, _) async => http.StreamedResponse(
                  Stream.value(const [123]),
                  401,
                  headers: const {'content-type': 'application/json'},
                )),
        onUnauthorized: refused.add);

    final response = await service.get(
        'http://home.test:4540/encore/cover/ar-1?size=256&p=pn_x&e=9&sig=old');

    expect(response.statusCode, 401,
        reason: 'the cache manager still fails it');
    expect(refused.single.queryParameters['sig'], 'old');
  });

  test('a good picture and a missing one are not "refused"', () async {
    var status = 200;
    final refused = <Uri>[];
    final service = CoverFileService(
        client:
            MockClient.streaming((request, _) async => http.StreamedResponse(
                  Stream.value(const [1]),
                  status,
                  headers: const {'cache-control': 'public'},
                )),
        onUnauthorized: refused.add);

    await service.get('http://home.test/encore/cover/al-1');
    status = 404;
    await service.get('http://home.test/encore/cover/al-2');

    expect(refused, isEmpty);
  });

  test('a response with no cache header is real art', () {
    expect(CoverFileService.isPlaceholder(const {}), isFalse);
    expect(
        CoverFileService.isPlaceholder(
            const {'cache-control': 'public, max-age=60'}),
        isFalse);
    expect(CoverFileService.isPlaceholder(const {'cache-control': 'No-Store'}),
        isTrue);
    expect(
        CoverFileService.isPlaceholder(
            const {'cache-control': 'private, no-store'}),
        isTrue);
  });
}
