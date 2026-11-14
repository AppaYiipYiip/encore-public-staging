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
  ///
  /// A picture that is an address (the catalogue's picture of a song the server keeps no file of) is the same image at every size and for every server:
  /// its key is the address, which is also what a catalogue result's picture is cached under.
  static String key(int serverId, String coverArtId, int size) =>
      coverArtId.startsWith('https://')
          ? 'url:$coverArtId'
          : 'cover:$serverId:$coverArtId:$size';
}

/// How much of a cover the phone fetches right now (P4-24): ONE rule for the background fetch on mobile data (small size only, a few
/// covers) and for the Data saver switch (every widget asks for the small size). The foreground and the background read the same two values
/// instead of each keeping its own numbers.
class CoverBudget {
  const CoverBudget({required this.smallOnly, required this.backgroundLimit});

  /// Both sizes, as many covers as a big library needs: Wi-Fi.
  static const full = CoverBudget(smallOnly: false, backgroundLimit: 600);

  /// The small size only, and at most this many covers in the background: a job nobody asked for must not eat a data plan (a big library is
  /// finished on Wi-Fi). Also what Data saver asks of every picture.
  static const mobile = CoverBudget(smallOnly: true, backgroundLimit: 120);

  final bool smallOnly;

  /// How many covers the background fetch keeps ready.
  final int backgroundLimit;

  /// The sizes the background fetch may ask for.
  List<int> get sizes => smallOnly
      ? const [CoverSize.small]
      : const [CoverSize.small, CoverSize.large];

  /// The fetch size for a widget that needs [px] device pixels.
  int fetchSize(int px) =>
      smallOnly ? CoverSize.small : CoverSize.forPixels(px);
}
