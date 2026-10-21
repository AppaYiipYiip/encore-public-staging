import 'package:encore/domain/audio_quality.dart';
import 'package:encore/playback/queue_model.dart';
import 'package:encore/playback/source_resolver.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late String? local;
  late bool exists;
  late AudioQuality quality;
  final built = <String>[];

  DefaultSourceResolver make() => DefaultSourceResolver(
        localPath: (_) async => local,
        streamUrl: (id, {maxBitRate, format}) async {
          final q = <String>[
            if (maxBitRate != null) 'maxBitRate=$maxBitRate',
            if (format != null) 'format=$format',
          ].join('&');
          built.add('$id?$q');
          return Uri.parse('https://srv/rest/stream?id=$id&$q');
        },
        streamQuality: () => quality,
        fileExists: (_) => exists,
      );

  QueueItem item({String suffix = 'flac', int bitRate = 900}) =>
      QueueItem(uid: 1, id: 'a', title: 'A', suffix: suffix, bitRate: bitRate);

  setUp(() {
    local = null;
    exists = true;
    quality = AudioQuality.original;
    built.clear();
  });

  test('a finished download is played from the file', () async {
    local = '/data/a.opus';
    final spec = await make().resolve(item());
    expect(spec.isLocal, isTrue);
    expect(spec.uri.scheme, 'file');
    expect(spec.uri.path, endsWith('/data/a.opus'));
    expect(built, isEmpty, reason: 'no URL is built for local files');
  });

  test('a missing file falls back to streaming', () async {
    local = '/data/gone.opus';
    exists = false;
    final spec = await make().resolve(item());
    expect(spec.isLocal, isFalse);
    expect(built, ['a?']);
  });

  test('original quality asks for the untouched stream', () async {
    final spec = await make().resolve(item());
    expect(spec.uri.queryParameters.containsKey('format'), isFalse);
    expect(spec.uri.queryParameters.containsKey('maxBitRate'), isFalse);
  });

  test('lossless source is transcoded to the chosen policy', () async {
    quality = AudioQuality.high;
    final spec = await make().resolve(item());
    expect(spec.uri.queryParameters['format'], 'opus');
    expect(spec.uri.queryParameters['maxBitRate'], '160');
  });

  test('a lossy source already below the cap is not re-encoded', () async {
    quality = AudioQuality.high;
    final spec = await make().resolve(item(suffix: 'mp3', bitRate: 128));
    expect(spec.uri.queryParameters.containsKey('format'), isFalse);
  });

  test('a lossy source above the cap is transcoded down', () async {
    quality = AudioQuality.normal;
    final spec = await make().resolve(item(suffix: 'mp3', bitRate: 320));
    expect(spec.uri.queryParameters['maxBitRate'], '96');
  });

  test('quality is read per resolve (network switches take effect)', () async {
    final r = make();
    quality = AudioQuality.original;
    var spec = await r.resolve(item());
    expect(spec.uri.queryParameters.containsKey('format'), isFalse);
    quality = AudioQuality.dataSaver;
    spec = await r.resolve(item());
    expect(spec.uri.queryParameters['maxBitRate'], '48');
  });
}
