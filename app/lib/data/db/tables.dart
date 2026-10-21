import 'package:drift/drift.dart';

/// Local database schema (docs/02-architecture.md section 3).
///
/// Conventions
/// * Every catalogue row is scoped by [serverId]; the primary key is
///   `(serverId, remoteId)` so bulk upserts need no id lookups.
/// * Timestamps are UTC epoch milliseconds (`...AtMs`) - portable and cheap to
///   compare/index.
/// * `syncRun` records the last sync run that *saw* the row; rows not seen by
///   a completed run are tombstoned (`deletedAtMs`), never hard-deleted first.
/// * `fingerprint` is a stable hash of the fields that matter for display and
///   audio; a changed fingerprint means "the song changed on the server".

/// A configured music server (credentials live in secure storage, keyed by
/// [id]).
@DataClassName('ServerRow')
class Servers extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get name => text()();
  TextColumn get username => text()();

  /// JSON list of `{ "label": "Home", "url": "http://192.168.1.2:4533" }`
  /// candidates; raced by the endpoint resolver (ADR-028).
  TextColumn get endpointsJson => text()();

  /// JSON map of detected capabilities (server type/version, OpenSubsonic
  /// extensions, native API availability).
  TextColumn get capabilitiesJson => text().withDefault(const Constant('{}'))();
  IntColumn get createdAtMs => integer()();
}

@DataClassName('ArtistRow')
@TableIndex(name: 'idx_artists_name', columns: {#serverId, #name})
class Artists extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get id => text()();
  TextColumn get name => text()();
  TextColumn get sortName => text().nullable()();
  TextColumn get coverArt => text().nullable()();
  IntColumn get albumCount => integer().withDefault(const Constant(0))();
  TextColumn get musicBrainzId => text().nullable()();
  TextColumn get imageUrl => text().nullable()();
  IntColumn get starredAtMs => integer().nullable()();
  TextColumn get fingerprint => text().withDefault(const Constant(''))();
  IntColumn get syncRun => integer().withDefault(const Constant(0))();
  IntColumn get deletedAtMs => integer().nullable()();

  @override
  Set<Column> get primaryKey => {serverId, id};
}

@DataClassName('AlbumRow')
@TableIndex(name: 'idx_albums_artist', columns: {#serverId, #artistId})
@TableIndex(name: 'idx_albums_created', columns: {#serverId, #createdAtMs})
@TableIndex(name: 'idx_albums_name', columns: {#serverId, #name})
class Albums extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get id => text()();
  TextColumn get artistId => text().nullable()();
  TextColumn get name => text()();
  TextColumn get sortName => text().nullable()();
  TextColumn get artist => text().nullable()();
  IntColumn get year => integer().nullable()();
  TextColumn get genre => text().nullable()();
  TextColumn get coverArt => text().nullable()();
  IntColumn get songCount => integer().withDefault(const Constant(0))();
  IntColumn get durationSec => integer().withDefault(const Constant(0))();
  TextColumn get musicBrainzId => text().nullable()();
  TextColumn get recordLabel => text().nullable()();
  BoolColumn get isCompilation =>
      boolean().withDefault(const Constant(false))();
  IntColumn get createdAtMs => integer().nullable()();
  IntColumn get starredAtMs => integer().nullable()();
  IntColumn get userRating => integer().nullable()();
  IntColumn get playCount => integer().nullable()();

  /// ARGB colour of the artwork (server-provided or computed once).
  IntColumn get dominantColor => integer().nullable()();
  TextColumn get thumbHash => text().nullable()();
  TextColumn get fingerprint => text().withDefault(const Constant(''))();
  IntColumn get syncRun => integer().withDefault(const Constant(0))();
  IntColumn get deletedAtMs => integer().nullable()();

  @override
  Set<Column> get primaryKey => {serverId, id};
}

@DataClassName('TrackRow')
@TableIndex(
  name: 'idx_tracks_album',
  columns: {#serverId, #albumId, #discNo, #trackNo},
)
@TableIndex(name: 'idx_tracks_artist', columns: {#serverId, #artistId})
@TableIndex(name: 'idx_tracks_starred', columns: {#serverId, #starredAtMs})
@TableIndex(name: 'idx_tracks_created', columns: {#serverId, #createdAtMs})
@TableIndex(name: 'idx_tracks_run', columns: {#serverId, #syncRun})
class Tracks extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get id => text()();
  TextColumn get albumId => text().nullable()();
  TextColumn get artistId => text().nullable()();
  TextColumn get title => text()();
  TextColumn get album => text().nullable()();
  TextColumn get artist => text().nullable()();
  IntColumn get trackNo => integer().nullable()();
  IntColumn get discNo => integer().nullable()();
  IntColumn get year => integer().nullable()();
  TextColumn get genre => text().nullable()();
  TextColumn get coverArt => text().nullable()();
  IntColumn get durationSec => integer().nullable()();
  IntColumn get size => integer().nullable()();
  TextColumn get suffix => text().nullable()();
  TextColumn get contentType => text().nullable()();
  IntColumn get bitRate => integer().nullable()();
  IntColumn get samplingRate => integer().nullable()();
  IntColumn get bitDepth => integer().nullable()();
  IntColumn get channels => integer().nullable()();
  TextColumn get path => text().nullable()();
  TextColumn get musicBrainzId => text().nullable()();
  TextColumn get isrc => text().nullable()();
  RealColumn get rgTrackGain => real().nullable()();
  RealColumn get rgAlbumGain => real().nullable()();
  RealColumn get rgTrackPeak => real().nullable()();
  RealColumn get rgAlbumPeak => real().nullable()();
  IntColumn get starredAtMs => integer().nullable()();
  IntColumn get userRating => integer().nullable()();
  IntColumn get playCount => integer().nullable()();
  IntColumn get createdAtMs => integer().nullable()();

  /// Server-side `updatedAt` (Navidrome native API) when known.
  IntColumn get serverUpdatedAtMs => integer().nullable()();

  /// Server reports the file as missing on disk (still in its database).
  BoolColumn get missing => boolean().withDefault(const Constant(false))();
  TextColumn get fingerprint => text().withDefault(const Constant(''))();

  /// Hash of the *audio-relevant* source properties (size, codec, bit rate,
  /// duration). A change here - not a mere tag edit - makes a downloaded copy
  /// stale (docs/02-architecture.md section 5.3).
  TextColumn get audioKey => text().withDefault(const Constant(''))();
  IntColumn get syncRun => integer().withDefault(const Constant(0))();
  IntColumn get deletedAtMs => integer().nullable()();

  @override
  Set<Column> get primaryKey => {serverId, id};
}

@DataClassName('PlaylistRow')
class Playlists extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get id => text()();
  TextColumn get name => text()();
  TextColumn get comment => text().nullable()();
  TextColumn get owner => text().nullable()();
  BoolColumn get isPublic => boolean().withDefault(const Constant(false))();

  /// Server-generated smart playlist (read-only, `validUntil` set).
  BoolColumn get readonly => boolean().withDefault(const Constant(false))();
  IntColumn get validUntilMs => integer().nullable()();
  TextColumn get coverArt => text().nullable()();
  IntColumn get songCount => integer().withDefault(const Constant(0))();
  IntColumn get durationSec => integer().withDefault(const Constant(0))();
  IntColumn get createdAtMs => integer().nullable()();
  IntColumn get changedAtMs => integer().nullable()();

  /// Hash of the *set* of track ids (order-insensitive); used to decide if a
  /// shuffled smart playlist really changed (ADR-025).
  TextColumn get memberSetHash => text().withDefault(const Constant(''))();
  IntColumn get entriesFetchedAtMs => integer().nullable()();

  /// `changedAt|songCount` of the server's playlist list entry that the stored
  /// [PlaylistEntries] were fetched for (v5). Written only when the songs are
  /// stored, so "are my songs stale?" is a comparison with what the phone really
  /// has. The metadata columns above are refreshed first, so comparing the
  /// server with them lost any playlist whose songs fetch was skipped or failed
  /// (docs/23, B5).
  TextColumn get entriesStamp => text().nullable()();
  IntColumn get syncRun => integer().withDefault(const Constant(0))();
  IntColumn get deletedAtMs => integer().nullable()();

  @override
  Set<Column> get primaryKey => {serverId, id};
}

@DataClassName('PlaylistEntryRow')
@TableIndex(name: 'idx_entries_track', columns: {#serverId, #trackId})
class PlaylistEntries extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get playlistId => text()();
  IntColumn get position => integer()();
  TextColumn get trackId => text()();

  @override
  Set<Column> get primaryKey => {serverId, playlistId, position};
}

/// User intent "keep this offline" (Spotify's Download toggle).
@DataClassName('PinRow')
class Pins extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();

  /// `playlist` | `album` | `artist` | `liked` | `track`.
  TextColumn get targetType => text()();
  TextColumn get targetId => text()();

  /// Download quality policy id (e.g. `original`, `opus160`).
  TextColumn get quality => text().withDefault(const Constant('original'))();
  IntColumn get createdAtMs => integer()();

  @override
  Set<Column> get primaryKey => {serverId, targetType, targetId};
}

/// Per-track download state.
@DataClassName('DownloadRow')
@TableIndex(name: 'idx_downloads_state', columns: {#serverId, #state})
class Downloads extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get trackId => text()();

  /// 0 queued, 1 downloading, 2 done, 3 failed.
  IntColumn get state => integer().withDefault(const Constant(0))();
  TextColumn get localPath => text().nullable()();
  IntColumn get bytes => integer().withDefault(const Constant(0))();
  IntColumn get expectedBytes => integer().nullable()();
  TextColumn get quality => text().withDefault(const Constant('original'))();

  /// `Tracks.audioKey` at download time; differs from the live value => stale.
  TextColumn get sourceAudioKey => text().withDefault(const Constant(''))();
  BoolColumn get stale => boolean().withDefault(const Constant(false))();
  TextColumn get lastError => text().nullable()();
  IntColumn get updatedAtMs => integer()();

  /// Set (v2) when no pin includes this track any more; the file is deleted
  /// once the grace period passes, so a smart playlist that is regenerated
  /// does not make the phone throw away and re-download the same songs.
  IntColumn get orphanedAtMs => integer().nullable()();

  /// Failed attempts since the last success (v2); drives retry back-off.
  IntColumn get attempts => integer().withDefault(const Constant(0))();

  @override
  Set<Column> get primaryKey => {serverId, trackId};
}

/// Pending local mutations to replay against the server (write-behind).
@DataClassName('OutboxRow')
@TableIndex(name: 'idx_outbox_due', columns: {#status, #nextAttemptAtMs})
class Outbox extends Table {
  IntColumn get id => integer().autoIncrement()();
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get kind => text()();
  TextColumn get payloadJson => text()();
  IntColumn get createdAtMs => integer()();
  IntColumn get attempts => integer().withDefault(const Constant(0))();

  /// Times the *server* rejected or failed this item (v5). Unlike [attempts]
  /// it does not count being offline, so a week without signal never parks an
  /// edit; it only bounds a server that keeps failing the same request.
  IntColumn get serverErrors => integer().withDefault(const Constant(0))();
  IntColumn get nextAttemptAtMs => integer().withDefault(const Constant(0))();

  /// `pending` | `failed`.
  TextColumn get status => text().withDefault(const Constant('pending'))();
  TextColumn get lastError => text().nullable()();
}

@DataClassName('PlayHistoryRow')
@TableIndex(name: 'idx_history_played', columns: {#serverId, #playedAtMs})
@TableIndex(name: 'idx_history_track', columns: {#serverId, #trackId})
class PlayHistory extends Table {
  IntColumn get id => integer().autoIncrement()();
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get trackId => text()();
  IntColumn get playedAtMs => integer()();
  IntColumn get listenedMs => integer().withDefault(const Constant(0))();
  TextColumn get source => text().nullable()();
}

@DataClassName('LyricsRow')
class Lyrics extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get trackId => text()();

  /// `synced` | `plain`.
  TextColumn get kind => text()();
  TextColumn get body => text()();
  TextColumn get source => text().nullable()();
  IntColumn get offsetMs => integer().withDefault(const Constant(0))();
  IntColumn get fetchedAtMs => integer()();

  @override
  Set<Column> get primaryKey => {serverId, trackId};
}

/// Per-server key/value state (sync watermarks etc.).
@DataClassName('SyncStateRow')
class SyncState extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get key => text()();
  TextColumn get value => text()();

  @override
  Set<Column> get primaryKey => {serverId, key};
}

@DataClassName('RecommendationCacheRow')
class RecommendationsCache extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get key => text()();
  TextColumn get payloadJson => text()();
  IntColumn get computedAtMs => integer()();

  @override
  Set<Column> get primaryKey => {serverId, key};
}

/// Artwork found in the public catalogue for albums whose server has no
/// cover (many YouTube-sourced libraries). `url == null` remembers "looked,
/// nothing found" so the lookup is not repeated on every scroll.
@DataClassName('CoverFallbackRow')
class CoverFallbacks extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();

  /// `normalizeForMatch(artist)|normalizeForMatch(title)`.
  TextColumn get key => text()();
  TextColumn get url => text().nullable()();
  IntColumn get fetchedAtMs => integer()();

  @override
  Set<Column> get primaryKey => {serverId, key};
}

/// Which server playlist a phone-only (`local-...`) playlist became once its
/// creation was delivered. A page that was opened under the local id keeps
/// working by looking the new id up here.
@DataClassName('PlaylistAliasRow')
class PlaylistAliases extends Table {
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();
  TextColumn get localId => text()();
  TextColumn get serverPlaylistId => text()();

  @override
  Set<Column> get primaryKey => {serverId, localId};
}

@DataClassName('RequestRow')
class Requests extends Table {
  IntColumn get id => integer().autoIncrement()();
  IntColumn get serverId =>
      integer().references(Servers, #id, onDelete: KeyAction.cascade)();

  /// `album` | `artist` | `import`.
  TextColumn get kind => text()();
  TextColumn get title => text()();
  TextColumn get artist => text()();
  TextColumn get album => text().nullable()();
  TextColumn get idsJson => text().withDefault(const Constant('{}'))();
  TextColumn get state => text()();
  TextColumn get detail => text().nullable()();
  IntColumn get createdAtMs => integer()();
  IntColumn get updatedAtMs => integer()();
}

/// Who is doing a piece of shared work right now (v5). The foreground app and
/// the periodic background job are two engines on one database file; each takes
/// a named lease before it syncs or delivers the outbox, so the same queued edit
/// is never sent twice and two dumps never remove each other's rows (docs/23, B2).
/// A lease expires on its own, so a killed process cannot hold it for ever.
@DataClassName('LeaseRow')
class Leases extends Table {
  /// e.g. `sync:1`, `outbox:1`.
  TextColumn get name => text()();

  /// A random id per engine instance.
  TextColumn get owner => text()();
  IntColumn get untilMs => integer()();

  @override
  Set<Column> get primaryKey => {name};
}
