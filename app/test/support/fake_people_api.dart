import 'package:encore/core/result.dart';
import 'package:encore/data/people/people_client.dart';

/// The people service as tests see it: answers from fields, records what the
/// app sent.
class FakePeopleApi implements PeopleApi {
  FakePeopleApi({
    this.me_ = const PeopleMe(user: 'sara', isAdmin: false, sharing: false),
  });

  PeopleMe me_;
  Result<void> sharingAnswer = const Result<void>.ok(null);
  final friendAnswers = <Result<List<FriendActivity>>>[];
  int friendCalls = 0;
  final sharingCalls = <bool>[];

  /// What [report] and [clear] were told, in order.
  final reports = <NowPlayingReport>[];
  int clears = 0;

  Result<CreatedInvite> createAnswer = Result.ok(CreatedInvite(
    id: 1,
    url: 'https://music.example.ts.net/people/join/abc',
    expiresAt: DateTime(2026, 10, 24),
  ));
  Result<List<InviteRow>> inviteList = const Result.ok([]);
  int createCalls = 0;
  PersonRole? lastInviteRole;
  final revoked = <int>[];

  /// Everybody on the server, as an owner sees them; [setRole] and
  /// [removePerson] change it the way the real service does.
  List<PersonOnServer> directory = [];
  Result<void> roleAnswer = const Result<void>.ok(null);
  Result<void> removeAnswer = const Result<void>.ok(null);
  final roleChanges = <(String, PersonRole)>[];
  final removed = <String>[];

  @override
  Future<Result<PeopleMe>> me() async => Result.ok(me_);

  @override
  Future<Result<List<FriendActivity>>> friends() async {
    friendCalls++;
    if (friendAnswers.isEmpty) return const Result.ok([]);
    return friendAnswers.length > 1
        ? friendAnswers.removeAt(0)
        : friendAnswers.first;
  }

  @override
  Future<Result<void>> setSharing(bool on) async {
    sharingCalls.add(on);
    return sharingAnswer;
  }

  @override
  Future<Result<CreatedInvite>> createInvite(
      {PersonRole role = PersonRole.guest}) async {
    createCalls++;
    lastInviteRole = role;
    return createAnswer;
  }

  @override
  Future<Result<List<InviteRow>>> invites() async => inviteList;

  @override
  Future<Result<void>> revokeInvite(int id) async {
    revoked.add(id);
    return const Result.ok(null);
  }

  @override
  Future<Result<List<PersonOnServer>>> people() async => Result.ok(directory);

  @override
  Future<Result<void>> setRole(String user, PersonRole role) async {
    roleChanges.add((user, role));
    if (roleAnswer.isOk) {
      directory = [
        for (final p in directory)
          if (p.user == user)
            PersonOnServer(
              user: p.user,
              role: role,
              isFounding: p.isFounding,
              invitedBy: p.invitedBy,
              joinedAt: p.joinedAt,
            )
          else
            p,
      ];
    }
    return roleAnswer;
  }

  @override
  Future<Result<void>> removePerson(String user) async {
    removed.add(user);
    if (removeAnswer.isOk) {
      directory = [
        for (final p in directory)
          if (p.user != user) p,
      ];
    }
    return removeAnswer;
  }

  @override
  Future<Result<void>> report(NowPlayingReport report) async {
    reports.add(report);
    return const Result.ok(null);
  }

  @override
  Future<Result<void>> clear() async {
    clears++;
    return const Result.ok(null);
  }
}

FriendActivity friendActivity(
  String user,
  String title, {
  String artist = 'Pink Floyd',
  bool playing = true,
}) =>
    FriendActivity(
      user: user,
      title: title,
      artist: artist,
      album: 'Animals',
      coverUrl: null,
      isPlaying: playing,
      startedAt: DateTime(2026, 10, 17),
    );
