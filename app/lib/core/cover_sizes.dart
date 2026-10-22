/// The two sizes a cover is ever fetched at.
///
/// A cover used to be fetched at the size of each widget (seven sizes), so a cover seen in a row (160 px) was not the one the
/// player (768 px) asked for: offline, one screen showed the album and the next a letter (E3). Now one cover is at most two cache
/// entries however many screens show it, and when only one of the two is cached (offline) it stands in for the other.
abstract final class CoverSize {
  /// Rows, the mini-player, small tiles, colour extraction.
  static const small = 256;

  /// Cards, grids, album pages, the player, the lock screen.
  static const large = 768;

  /// The fetch size for a widget that needs [px] device pixels.
  static int forPixels(int px) => px <= 320 ? small : large;

  /// The other size: the one that stands in when [size] is not cached.
  static int otherThan(int size) => size == small ? large : small;

  /// The disk-cache key of a cover of this server at [size]. It never holds credentials (ADR-017).
  static String key(int serverId, String coverArtId, int size) =>
      'cover:$serverId:$coverArtId:$size';
}
