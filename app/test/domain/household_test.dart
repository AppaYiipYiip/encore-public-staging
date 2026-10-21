import 'package:encore/domain/household.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('playlistOwnership', () {
    PlaylistOwnership of(String? owner,
            {bool readonly = false, String? me = 'marwa'}) =>
        playlistOwnership(owner: owner, readonly: readonly, me: me);

    test('a playlist the account made is mine', () {
      expect(of('marwa'), PlaylistOwnership.mine);
    });

    test('case and stray spaces do not matter', () {
      expect(of('Marwa'), PlaylistOwnership.mine);
      expect(of(' marwa '), PlaylistOwnership.mine);
    });

    test('a server-generated playlist of mine is "made for me"', () {
      expect(of('marwa', readonly: true), PlaylistOwnership.madeForMe);
    });

    test('someone else\'s playlist is shared - generated or not', () {
      expect(of('sara'), PlaylistOwnership.shared);
      expect(of('sara', readonly: true), PlaylistOwnership.shared);
    });

    test('an unknown owner or account counts as mine', () {
      expect(of(null), PlaylistOwnership.mine);
      expect(of(null, readonly: true), PlaylistOwnership.madeForMe);
      expect(of('sara', me: null), PlaylistOwnership.mine,
          reason: 'before the account is known nothing is hidden');
    });
  });

  group('LibraryScope', () {
    test('is read back by name; unknown values fall back to automatic', () {
      expect(LibraryScope.byName('everything'), LibraryScope.everything);
      expect(LibraryScope.byName('mine'), LibraryScope.mine);
      expect(LibraryScope.byName('automatic'), LibraryScope.automatic);
      expect(LibraryScope.byName(null), LibraryScope.automatic);
      expect(LibraryScope.byName('whatever'), LibraryScope.automatic);
    });
  });

  group('MyMusic', () {
    test('compares by content so unchanged answers are not re-emitted', () {
      const a = MyMusic(albumIds: {'1', '2'}, artistIds: {'x'});
      const b = MyMusic(albumIds: {'2', '1'}, artistIds: {'x'});
      const c = MyMusic(albumIds: {'1'}, artistIds: {'x'});
      expect(a, b);
      expect(a.hashCode, b.hashCode);
      expect(a == c, isFalse);
    });

    test('answers membership questions, tolerating a missing artist id', () {
      const mine = MyMusic(albumIds: {'al1'}, artistIds: {'ar1'});
      expect(mine.hasAlbum('al1'), isTrue);
      expect(mine.hasAlbum('al2'), isFalse);
      expect(mine.hasArtist('ar1'), isTrue);
      expect(mine.hasArtist(null), isFalse);
      expect(MyMusic.empty.isEmpty, isTrue);
    });
  });
}
