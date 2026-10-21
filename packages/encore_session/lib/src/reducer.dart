/// The one place that decides what a command does to a session
/// (docs/29, docs/30). Pure and deterministic: the hub calls it with the hub
/// clock, the tests call it with a number.
///
/// The rules are Spotify Jam's and nothing more: everybody in the session can
/// add songs, reorder and remove them, pause, skip and seek; only the host
/// controls the volume, picks the speaker and removes people.
library;

import 'protocol.dart';

/// The result of applying a command: a new state, or the reason it was
/// refused (in which case [state] is the unchanged input).
class Outcome {
  const Outcome.accepted(this.state) : rejected = null;
  const Outcome.refused(this.state, String this.rejected);

  final SessionState state;
  final String? rejected;

  bool get ok => rejected == null;
}

/// A plain-words reason, or `null` when [actor] may do [command].
String? denial(Member actor, Command command) {
  switch (command) {
    case SetVolume() || Transfer() || Kick():
      return actor.isHost ? null : 'only the host can do that';
    case Play() ||
          Pause() ||
          Seek() ||
          Next() ||
          Previous() ||
          SetRepeat() ||
          Add() ||
          Remove() ||
          Move() ||
          Jump() ||
          Ended():
      return null;
  }
}

SessionState _bump(SessionState s) => s.copyWith(rev: s.rev + 1);

SessionState _at(SessionState s, int hubMs, int posMs) =>
    s.copyWith(anchor: Anchor(hubMs, posMs));

/// Moves to queue position [index] with the clock restarted.
SessionState _goTo(SessionState s, int index, int nowHubMs) =>
    s.copyWith(index: index, anchor: Anchor(nowHubMs, 0));

SessionState _skipForward(SessionState s, int nowHubMs) {
  if (s.queue.isEmpty) return s;
  if (s.index + 1 < s.queue.length) return _goTo(s, s.index + 1, nowHubMs);
  if (s.repeat == Repeat.all) return _goTo(s, 0, nowHubMs);
  // The end of the queue: stop on the last song, ready to replay.
  return s.copyWith(playing: false, anchor: Anchor(nowHubMs, 0));
}

Outcome reduce(
  SessionState state,
  Command command, {
  required String actorId,
  required int nowHubMs,
}) {
  Outcome no(String why) => Outcome.refused(state, why);
  Outcome yes(SessionState next) => identical(next, state)
      ? Outcome.accepted(state)
      : Outcome.accepted(_bump(next));

  if (state.ended) return no('the session has ended');
  final actor = state.member(actorId);
  if (actor == null) return no('you are not in this session');
  final denied = denial(actor, command);
  if (denied != null) return no(denied);

  final position = state.positionAt(nowHubMs);
  switch (command) {
    case Play():
      if (state.queue.isEmpty) return no('there is nothing to play');
      if (state.playing) return yes(state);
      return yes(
          state.copyWith(playing: true, anchor: Anchor(nowHubMs, position)));
    case Pause():
      if (!state.playing) return yes(state);
      return yes(
          state.copyWith(playing: false, anchor: Anchor(nowHubMs, position)));
    case Seek(:final posMs):
      if (state.queue.isEmpty) return no('there is nothing to play');
      return yes(_at(state, nowHubMs, posMs));
    case Next():
      return yes(_skipForward(state, nowHubMs));
    case Previous():
      if (state.queue.isEmpty) return no('there is nothing to play');
      if (position > 3000 || state.index == 0) {
        return yes(_at(state, nowHubMs, 0));
      }
      return yes(_goTo(state, state.index - 1, nowHubMs));
    case SetVolume(:final level):
      return yes(state.copyWith(volume: level));
    case SetRepeat(:final mode):
      return yes(state.copyWith(repeat: mode));
    case Transfer(:final deviceId):
      return yes(state.copyWith(playerDeviceId: deviceId));
    case Add(
        :final trackId,
        :final at,
        :final title,
        :final artist,
        :final album,
        :final durationSec,
        :final imageUrl,
        :final artistRef
      ):
      if (state.queue.length >= maxQueue) return no('the queue is full');
      final entry = QueueEntry(
        uid: state.nextUid,
        trackId: trackId,
        addedBy: actorId,
        title: title,
        artist: artist,
        album: album,
        durationSec: durationSec,
        imageUrl: imageUrl,
        artistRef: artistRef,
      );
      if (state.queue.isEmpty) {
        return yes(state.copyWith(
            queue: [entry],
            index: 0,
            nextUid: state.nextUid + 1,
            playing: at == AddAt.now ? true : state.playing,
            anchor: Anchor(nowHubMs, 0)));
      }
      final where = at == AddAt.end ? state.queue.length : state.index + 1;
      final queue = [...state.queue]..insert(where, entry);
      if (at == AddAt.now) {
        // The song just added is the one that plays, from its start.
        return yes(state.copyWith(
            queue: queue,
            index: where,
            nextUid: state.nextUid + 1,
            playing: true,
            anchor: Anchor(nowHubMs, 0)));
      }
      return yes(state.copyWith(queue: queue, nextUid: state.nextUid + 1));
    case Jump(:final uid):
      final to = state.queue.indexWhere((e) => e.uid == uid);
      if (to < 0) return no('no such song in the queue');
      return yes(_goTo(state, to, nowHubMs).copyWith(playing: true));
    case Remove(:final uid):
      final at = state.queue.indexWhere((e) => e.uid == uid);
      if (at < 0) return no('no such song in the queue');
      final queue = [...state.queue]..removeAt(at);
      if (queue.isEmpty) {
        return yes(state.copyWith(
            queue: queue,
            index: 0,
            playing: false,
            anchor: Anchor(nowHubMs, 0)));
      }
      if (at < state.index) {
        return yes(state.copyWith(queue: queue, index: state.index - 1));
      }
      if (at > state.index) return yes(state.copyWith(queue: queue));
      // The current song was removed: the next one takes its place.
      final index = state.index < queue.length ? state.index : 0;
      return yes(_goTo(state.copyWith(queue: queue), index, nowHubMs));
    case Move(:final uid, :final to):
      final from = state.queue.indexWhere((e) => e.uid == uid);
      if (from < 0) return no('no such song in the queue');
      final target = to.clamp(0, state.queue.length - 1);
      if (from == target) return yes(state);
      final currentUid = state.current?.uid;
      final queue = [...state.queue];
      final moved = queue.removeAt(from);
      queue.insert(target, moved);
      final index = currentUid == null
          ? state.index
          : queue.indexWhere((e) => e.uid == currentUid);
      return yes(state.copyWith(queue: queue, index: index));
    case Ended(:final uid):
      // Everybody who plays says so at about the same moment: only the first
      // report, about the song that is really playing, moves the queue.
      if (!state.playing || state.current?.uid != uid) return yes(state);
      if (state.repeat == Repeat.one) {
        return yes(_goTo(state, state.index, nowHubMs));
      }
      return yes(_skipForward(state, nowHubMs));
    case Kick(:final memberId):
      final target = state.member(memberId);
      if (target == null) return no('that person is not in this session');
      if (target.isHost) return no('the host cannot be removed');
      return yes(_without(state, memberId));
  }
}

SessionState _without(SessionState s, String memberId) => s.copyWith(
      members: [
        for (final m in s.members)
          if (m.id != memberId) m
      ],
    );

/// A person joins. Refused when the session is full or has ended.
Outcome join(SessionState state, Member member) {
  if (state.ended) return Outcome.refused(state, 'the session has ended');
  if (state.member(member.id) != null) return Outcome.accepted(state);
  if (state.members.length >= maxPeople) {
    return Outcome.refused(state, 'the session is full');
  }
  return Outcome.accepted(
      _bump(state.copyWith(members: [...state.members, member])));
}

/// A person leaves (or was removed). The session ends when the host goes.
Outcome leave(SessionState state, String memberId) {
  final who = state.member(memberId);
  if (who == null) return Outcome.accepted(state);
  final without = _without(state, memberId);
  return Outcome.accepted(_bump(
      who.isHost ? without.copyWith(ended: true, playing: false) : without));
}
