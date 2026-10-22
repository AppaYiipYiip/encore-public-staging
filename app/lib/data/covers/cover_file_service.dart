import 'dart:async';

import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:http/http.dart' as http;

import '../../core/logger.dart';

/// Fetches pictures for the cover cache, and refuses the blank record the music server makes up for an album it has no art for.
///
/// That placeholder is a perfectly good picture to a file cache, so it was stored for a year under the album's id, and an album whose art was
/// added later (the id does not change) kept showing it. The music server marks it `Cache-Control: no-store`; here that makes the fetch fail,
/// so the screen shows its own fallback (the catalogue's cover, a collage, the monogram) and nothing is stored.
class CoverFileService extends FileService {
  CoverFileService({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  /// Whether these response headers are the music server's "no picture" marker.
  static bool isPlaceholder(Map<String, String> headers) =>
      (headers['cache-control'] ?? '')
          .toLowerCase()
          .split(',')
          .any((part) => part.trim() == 'no-store');

  @override
  Future<FileServiceResponse> get(String url,
      {Map<String, String>? headers}) async {
    final request = http.Request('GET', Uri.parse(url));
    if (headers != null) request.headers.addAll(headers);
    final response = await _client.send(request);
    if (isPlaceholder(response.headers)) {
      // Nobody reads this body: let it go.
      unawaited(response.stream.drain<void>().then<void>((_) {},
          onError: (Object error) => Log.debug(
              'covers', 'a refused picture was not read out: $error')));
      throw HttpExceptionWithStatus(404, 'The server has no picture for this.',
          uri: request.url);
    }
    return HttpGetResponse(response);
  }
}
