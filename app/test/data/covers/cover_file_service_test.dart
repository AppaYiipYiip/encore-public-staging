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
