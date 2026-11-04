import 'package:encore/domain/album_names.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('isCatchAllAlbum', () {
    test('the music server\'s bucket for songs with no album is one', () {
      expect(isCatchAllAlbum('[Unknown Album]'), isTrue);
    });

    test('case and stray spaces do not matter', () {
      expect(isCatchAllAlbum('  [unknown album] '), isTrue);
      expect(isCatchAllAlbum('[UNKNOWN ALBUM]'), isTrue);
    });

    test('a real album is not, even when its name says "unknown"', () {
      expect(isCatchAllAlbum('Unknown Pleasures'), isFalse);
      expect(isCatchAllAlbum('Unknown Album Vol. 2'), isFalse);
      expect(isCatchAllAlbum('Lateralus'), isFalse);
    });

    test('nothing at all is not an album to hide', () {
      expect(isCatchAllAlbum(null), isFalse);
      expect(isCatchAllAlbum(''), isFalse);
    });
  });

  group('albumDisplayName', () {
    test('the bucket is named in plain words', () {
      expect(albumDisplayName('[Unknown Album]'), 'Songs without an album');
    });

    test('a real album keeps its own name, untouched', () {
      expect(albumDisplayName('Lateralus'), 'Lateralus');
      expect(albumDisplayName(' Spaced '), ' Spaced ');
    });
  });

  group('withoutCatchAllAlbums', () {
    test('keeps the releases, drops the bucket, keeps the order', () {
      final names = [
        'Lateralus',
        '[Unknown Album]',
        'Damnation',
        '[Unknown Album]'
      ];
      expect(
          withoutCatchAllAlbums(names, (n) => n), ['Lateralus', 'Damnation']);
    });

    test('an empty list stays empty', () {
      expect(withoutCatchAllAlbums(const <String>[], (n) => n), isEmpty);
    });
  });
}
