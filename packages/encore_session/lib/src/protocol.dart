/// The vocabulary of Devices and Sessions (docs/29, docs/22 section 3).
///
/// Pure Dart: no Flutter, no `dart:io`. The same file is used by the app, by
/// the tests and (compiled to JavaScript) by the web listener, so it never
/// throws on malformed input: every `fromJson` returns `null` instead.
library;

import 'package:meta/meta.dart';

/// Spotify's Jam has no per-action rules, and neither do we (docs/30): the
/// only limits are sizes.
const int maxPeople = 32;
const int maxQueue = 500;

/// What can be asked of a session.
enum Op {
  play,
  pause,
  seek,
  next,
  previous,
  setVolume,
  setRepeat,
  add,
  remove,
  move,
  transfer,
  kick,

  /// "The song with this id finished playing": said by every phone that plays,
  /// applied once (the queue moves on only if that song is still the current one).
  ended,

  /// "Play this song of the queue now".
  jump,
}

enum Repeat { off, all, one }

/// Where an added song goes: last, right after the current one, or **now**:
/// right after the current one, which becomes the current one and plays (a
/// person who plays a song while in a Jam plays it in the Jam).
enum AddAt { end, next, now }

enum Role { host, member }

T? _enumByName<T extends Enum>(List<T> values, Object? name) {
  if (name is! String) return null;
  for (final value in values) {
    if (value.name == name) return value;
  }
  return null;
}

int? _int(Object? value, {int min = -0x7fffffff, int max = 0x7fffffff}) {
  if (value is! int) return null;
  if (value < min || value > max) return null;
  return value;
}

/// Absent, or text of a sensible length (an empty string counts as absent).
bool _optionalText(Object? value, {int maxLength = 200}) =>
    value == null || (value is String && value.length <= maxLength);

/// Absent, or a whole number from 0 up to [max].
bool _optionalInt(Object? value, {required int max}) =>
    value == null || (value is int && value >= 0 && value <= max);

String? _string(Object? value, {int maxLength = 200}) {
  if (value is! String || value.isEmpty || value.length > maxLength) {
    return null;
  }
  return value;
}

/// A person in a session.
@immutable
class Member {
  const Member({
    required this.id,
    required this.name,
    this.role = Role.member,
  });

  final String id;
  final String name;
  final Role role;

  bool get isHost => role == Role.host;

  Map<String, Object?> toJson() => {'id': id, 'name': name, 'role': role.name};

  static Member? fromJson(Object? json) {
    if (json is! Map<String, Object?>) return null;
    final id = _string(json['id'], maxLength: 64);
    final name = _string(json['name'], maxLength: 40);
    final role = _enumByName(Role.values, json['role']);
    if (id == null || name == null || role == null) return null;
    return Member(id: id, name: name, role: role);
  }

  @override
  bool operator ==(Object other) =>
      other is Member &&
      other.id == id &&
      other.name == name &&
      other.role == role;

  @override
  int get hashCode => Object.hash(id, name, role);
}

/// One song in the shared queue. Only ids travel: every device has the
/// library, so titles and covers come from its own copy.
@immutable
class QueueEntry {
  const QueueEntry({
    required this.uid,
    required this.trackId,
    required this.addedBy,
    this.title,
    this.artist,
    this.album,
    this.durationSec,
    this.imageUrl,
    this.artistRef,
  });

  /// Unique inside the session; stable while the entry moves.
  final int uid;

  /// The id of the song in the library of the person who added it. It means
  /// nothing in another person's library (each person on a server has their
  /// own), so it is only a hint: [title] and [artist] are what a phone finds
  /// the song by.
  final String trackId;

  /// The [Member.id] who added it.
  final String addedBy;

  /// What the song is, for showing it and for finding or fetching it on the
  /// phone that plays. Absent on entries from phones that do not send them.
  final String? title;
  final String? artist;
  final String? album;

  /// What a screen needs to show the song on a phone that has none of it: how
  /// long it is, a cover (a web address any phone can read) and the catalogue
  /// id of the artist, to open their page.
  final int? durationSec;
  final String? imageUrl;
  final String? artistRef;

  Map<String, Object?> toJson() => {
        'uid': uid,
        'trackId': trackId,
        'addedBy': addedBy,
        if (title != null) 'title': title,
        if (artist != null) 'artist': artist,
        if (album != null) 'album': album,
        if (durationSec != null) 'durationSec': durationSec,
        if (imageUrl != null) 'imageUrl': imageUrl,
        if (artistRef != null) 'artistRef': artistRef,
      };

  static QueueEntry? fromJson(Object? json) {
    if (json is! Map<String, Object?>) return null;
    final uid = _int(json['uid'], min: 0);
    final trackId = _string(json['trackId'], maxLength: 128);
    final addedBy = _string(json['addedBy'], maxLength: 64);
    if (uid == null || trackId == null || addedBy == null) return null;
    if (!_optionalText(json['title']) ||
        !_optionalText(json['artist']) ||
        !_optionalText(json['album']) ||
        !_optionalText(json['imageUrl'], maxLength: 400) ||
        !_optionalText(json['artistRef'], maxLength: 64) ||
        !_optionalInt(json['durationSec'], max: 86400)) {
      return null;
    }
    return QueueEntry(
      uid: uid,
      trackId: trackId,
      addedBy: addedBy,
      title: json['title'] as String?,
      artist: json['artist'] as String?,
      album: json['album'] as String?,
      durationSec: json['durationSec'] as int?,
      imageUrl: json['imageUrl'] as String?,
      artistRef: json['artistRef'] as String?,
    );
  }

  @override
  bool operator ==(Object other) =>
      other is QueueEntry &&
      other.uid == uid &&
      other.trackId == trackId &&
      other.addedBy == addedBy &&
      other.title == title &&
      other.artist == artist &&
      other.album == album &&
      other.durationSec == durationSec &&
      other.imageUrl == imageUrl &&
      other.artistRef == artistRef;

  @override
  int get hashCode => Object.hash(uid, trackId, addedBy, title, artist, album,
      durationSec, imageUrl, artistRef);
}

/// "At hub time [hubMs] the current song was at [posMs]."
@immutable
class Anchor {
  const Anchor(this.hubMs, this.posMs);

  final int hubMs;
  final int posMs;

  @override
  bool operator ==(Object other) =>
      other is Anchor && other.hubMs == hubMs && other.posMs == posMs;

  @override
  int get hashCode => Object.hash(hubMs, posMs);
}

/// Everything a device needs to show and to play a session. A snapshot, not
/// a log: a lost or repeated message cannot corrupt anything, a device keeps
/// the highest [rev].
@immutable
class SessionState {
  const SessionState({
    this.rev = 0,
    this.queue = const [],
    this.index = 0,
    this.playing = false,
    this.anchor = const Anchor(0, 0),
    this.playerDeviceId,
    this.volume = 100,
    this.repeat = Repeat.off,
    this.members = const [],
    this.nextUid = 1,
    this.ended = false,
  });

  final int rev;
  final List<QueueEntry> queue;

  /// Index of the current song in [queue]; meaningless when it is empty.
  final int index;
  final bool playing;
  final Anchor anchor;

  /// The device whose speaker is used, if any.
  final String? playerDeviceId;

  /// 0-100, the player's own volume.
  final int volume;
  final Repeat repeat;
  final List<Member> members;
  final int nextUid;
  final bool ended;

  QueueEntry? get current =>
      index >= 0 && index < queue.length ? queue[index] : null;

  Member? member(String id) {
    for (final m in members) {
      if (m.id == id) return m;
    }
    return null;
  }

  /// Where the current song is at hub time [nowHubMs].
  int positionAt(int nowHubMs) {
    if (!playing) return anchor.posMs;
    final elapsed = nowHubMs - anchor.hubMs;
    return anchor.posMs + (elapsed < 0 ? 0 : elapsed);
  }

  SessionState copyWith({
    int? rev,
    List<QueueEntry>? queue,
    int? index,
    bool? playing,
    Anchor? anchor,
    Object? playerDeviceId = _keep,
    int? volume,
    Repeat? repeat,
    List<Member>? members,
    int? nextUid,
    bool? ended,
  }) =>
      SessionState(
        rev: rev ?? this.rev,
        queue: queue ?? this.queue,
        index: index ?? this.index,
        playing: playing ?? this.playing,
        anchor: anchor ?? this.anchor,
        playerDeviceId: identical(playerDeviceId, _keep)
            ? this.playerDeviceId
            : playerDeviceId as String?,
        volume: volume ?? this.volume,
        repeat: repeat ?? this.repeat,
        members: members ?? this.members,
        nextUid: nextUid ?? this.nextUid,
        ended: ended ?? this.ended,
      );

  Map<String, Object?> toJson() => {
        'rev': rev,
        'queue': [for (final e in queue) e.toJson()],
        'index': index,
        'playing': playing,
        'anchor': {'hubMs': anchor.hubMs, 'posMs': anchor.posMs},
        'player': playerDeviceId,
        'volume': volume,
        'repeat': repeat.name,
        'members': [for (final m in members) m.toJson()],
        'nextUid': nextUid,
        'ended': ended,
      };

  static SessionState? fromJson(Object? json) {
    if (json is! Map<String, Object?>) return null;
    final rev = _int(json['rev'], min: 0);
    final index = _int(json['index'], min: 0);
    final playing = json['playing'];
    final anchorJson = json['anchor'];
    final volume = _int(json['volume'], min: 0, max: 100);
    final repeat = _enumByName(Repeat.values, json['repeat']);
    final nextUid = _int(json['nextUid'], min: 1);
    final ended = json['ended'];
    final player = json['player'];
    final queueJson = json['queue'];
    final membersJson = json['members'];
    if (rev == null ||
        index == null ||
        playing is! bool ||
        anchorJson is! Map<String, Object?> ||
        volume == null ||
        repeat == null ||
        nextUid == null ||
        ended is! bool ||
        (player != null && _string(player, maxLength: 64) == null) ||
        queueJson is! List<Object?> ||
        membersJson is! List<Object?>) {
      return null;
    }
    final hubMs = _int(anchorJson['hubMs']);
    final posMs = _int(anchorJson['posMs'], min: 0);
    if (hubMs == null || posMs == null) return null;
    if (queueJson.length > maxQueue || membersJson.length > maxPeople) {
      return null;
    }
    final queue = <QueueEntry>[];
    for (final item in queueJson) {
      final entry = QueueEntry.fromJson(item);
      if (entry == null) return null;
      queue.add(entry);
    }
    final members = <Member>[];
    for (final item in membersJson) {
      final member = Member.fromJson(item);
      if (member == null) return null;
      members.add(member);
    }
    return SessionState(
      rev: rev,
      queue: queue,
      index: index,
      playing: playing,
      anchor: Anchor(hubMs, posMs),
      playerDeviceId: player as String?,
      volume: volume,
      repeat: repeat,
      members: members,
      nextUid: nextUid,
      ended: ended,
    );
  }
}

const Object _keep = Object();

/// A request from a device. The hub checks it against the session's rules.
@immutable
sealed class Command {
  const Command();

  Op get op;

  Map<String, Object?> toJson();

  /// `null` for anything that is not a well-formed command.
  static Command? fromJson(Object? json) {
    if (json is! Map<String, Object?>) return null;
    final op = _enumByName(Op.values, json['op']);
    if (op == null) return null;
    switch (op) {
      case Op.play:
        return const Play();
      case Op.pause:
        return const Pause();
      case Op.next:
        return const Next();
      case Op.previous:
        return const Previous();
      case Op.seek:
        final pos = _int(json['posMs'], min: 0, max: 86400000);
        return pos == null ? null : Seek(pos);
      case Op.setVolume:
        final level = _int(json['level'], min: 0, max: 100);
        return level == null ? null : SetVolume(level);
      case Op.setRepeat:
        final mode = _enumByName(Repeat.values, json['mode']);
        return mode == null ? null : SetRepeat(mode);
      case Op.add:
        final trackId = _string(json['trackId'], maxLength: 128);
        final at = _enumByName(AddAt.values, json['at'] ?? AddAt.end.name);
        if (trackId == null || at == null) return null;
        if (!_optionalText(json['title']) ||
            !_optionalText(json['artist']) ||
            !_optionalText(json['album']) ||
            !_optionalText(json['imageUrl'], maxLength: 400) ||
            !_optionalText(json['artistRef'], maxLength: 64) ||
            !_optionalInt(json['durationSec'], max: 86400)) {
          return null;
        }
        return Add(
          trackId,
          at: at,
          title: json['title'] as String?,
          artist: json['artist'] as String?,
          album: json['album'] as String?,
          durationSec: json['durationSec'] as int?,
          imageUrl: json['imageUrl'] as String?,
          artistRef: json['artistRef'] as String?,
        );
      case Op.jump:
        final uid = _int(json['uid'], min: 0);
        return uid == null ? null : Jump(uid);
      case Op.remove:
        final uid = _int(json['uid'], min: 0);
        return uid == null ? null : Remove(uid);
      case Op.move:
        final uid = _int(json['uid'], min: 0);
        final to = _int(json['to'], min: 0, max: 1000);
        return uid == null || to == null ? null : Move(uid, to);
      case Op.transfer:
        final device = _string(json['deviceId'], maxLength: 64);
        return device == null ? null : Transfer(device);
      case Op.kick:
        final id = _string(json['memberId'], maxLength: 64);
        return id == null ? null : Kick(id);
      case Op.ended:
        final uid = _int(json['uid'], min: 0);
        return uid == null ? null : Ended(uid);
    }
  }
}

class Play extends Command {
  const Play();
  @override
  Op get op => Op.play;
  @override
  Map<String, Object?> toJson() => {'op': op.name};
}

class Pause extends Command {
  const Pause();
  @override
  Op get op => Op.pause;
  @override
  Map<String, Object?> toJson() => {'op': op.name};
}

class Next extends Command {
  const Next();
  @override
  Op get op => Op.next;
  @override
  Map<String, Object?> toJson() => {'op': op.name};
}

class Previous extends Command {
  const Previous();
  @override
  Op get op => Op.previous;
  @override
  Map<String, Object?> toJson() => {'op': op.name};
}

class Seek extends Command {
  const Seek(this.posMs);
  final int posMs;
  @override
  Op get op => Op.seek;
  @override
  Map<String, Object?> toJson() => {'op': op.name, 'posMs': posMs};
}

class SetVolume extends Command {
  const SetVolume(this.level);
  final int level;
  @override
  Op get op => Op.setVolume;
  @override
  Map<String, Object?> toJson() => {'op': op.name, 'level': level};
}

class SetRepeat extends Command {
  const SetRepeat(this.mode);
  final Repeat mode;
  @override
  Op get op => Op.setRepeat;
  @override
  Map<String, Object?> toJson() => {'op': op.name, 'mode': mode.name};
}

class Add extends Command {
  const Add(this.trackId,
      {this.at = AddAt.end,
      this.title,
      this.artist,
      this.album,
      this.durationSec,
      this.imageUrl,
      this.artistRef});
  final String trackId;
  final AddAt at;

  /// What the song is (see [QueueEntry.title]).
  final String? title;
  final String? artist;
  final String? album;
  final int? durationSec;
  final String? imageUrl;
  final String? artistRef;
  @override
  Op get op => Op.add;
  @override
  Map<String, Object?> toJson() => {
        'op': op.name,
        'trackId': trackId,
        'at': at.name,
        if (title != null) 'title': title,
        if (artist != null) 'artist': artist,
        if (album != null) 'album': album,
        if (durationSec != null) 'durationSec': durationSec,
        if (imageUrl != null) 'imageUrl': imageUrl,
        if (artistRef != null) 'artistRef': artistRef,
      };
}

/// Play the song [uid] of the queue now, from its start.
class Jump extends Command {
  const Jump(this.uid);
  final int uid;
  @override
  Op get op => Op.jump;
  @override
  Map<String, Object?> toJson() => {'op': op.name, 'uid': uid};
}

class Remove extends Command {
  const Remove(this.uid);
  final int uid;
  @override
  Op get op => Op.remove;
  @override
  Map<String, Object?> toJson() => {'op': op.name, 'uid': uid};
}

class Move extends Command {
  const Move(this.uid, this.to);
  final int uid;

  /// The new index in the queue.
  final int to;
  @override
  Op get op => Op.move;
  @override
  Map<String, Object?> toJson() => {'op': op.name, 'uid': uid, 'to': to};
}

class Transfer extends Command {
  const Transfer(this.deviceId);
  final String deviceId;
  @override
  Op get op => Op.transfer;
  @override
  Map<String, Object?> toJson() => {'op': op.name, 'deviceId': deviceId};
}

class Kick extends Command {
  const Kick(this.memberId);
  final String memberId;
  @override
  Op get op => Op.kick;
  @override
  Map<String, Object?> toJson() => {'op': op.name, 'memberId': memberId};
}

/// The song [uid] reached its end on a phone that was playing it.
class Ended extends Command {
  const Ended(this.uid);
  final int uid;
  @override
  Op get op => Op.ended;
  @override
  Map<String, Object?> toJson() => {'op': op.name, 'uid': uid};
}
