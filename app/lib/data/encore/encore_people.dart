import '../../core/result.dart';
import '../people/people_client.dart';
import 'encore_api.dart';

/// People and invitations on an Encore server, in the shape the people screens already use ([PeopleApi]).
///
/// The server has two roles, an owner and a member; the screens' "guest" is a member (neither can make invitations). Friend activity is not
/// part of this server yet: nothing is shared and the list of friends is empty.
class EncorePeopleApi implements PeopleApi {
  EncorePeopleApi({required EncoreApi api, required Uri Function() address})
      : _api = api,
        _address = address;

  final EncoreApi _api;
  final Uri Function() _address;

  /// The ids of the people seen last, by user name (the people screens speak of names, the server of ids).
  final Map<String, String> _ids = {};

  /// The link an invitation is sent as: the address of the server, so it opens the app on the invited person's phone.
  static Uri joinLink(Uri server, String code) {
    final front = server.path.replaceAll(RegExp(r'/+$'), '');
    return Uri(
        scheme: server.scheme,
        host: server.host,
        port: server.hasPort ? server.port : null,
        path: '$front/encore/join/$code');
  }

  static PersonRole _role(String wire) =>
      wire == 'owner' ? PersonRole.owner : PersonRole.guest;

  static String _wire(PersonRole role) =>
      role == PersonRole.owner ? 'owner' : 'member';

  static DateTime _time(int ms) => DateTime.fromMillisecondsSinceEpoch(ms);

  @override
  Future<Result<PeopleMe>> me() async {
    final result = await _api.me();
    final me = result.valueOrNull;
    if (me == null) return Result.err(result.failureOrNull!);
    return Result.ok(PeopleMe(
      user: me.username,
      isAdmin: me.isOwner,
      sharing: false,
      role: _role(me.role),
      canInvite: me.isOwner,
      canManage: me.isOwner,
    ));
  }

  @override
  Future<Result<List<FriendActivity>>> friends() async =>
      const Result.ok(<FriendActivity>[]);

  @override
  Future<Result<void>> setSharing(bool on) async => const Result.ok(null);

  @override
  Future<Result<void>> report(NowPlayingReport report) async =>
      const Result.ok(null);

  @override
  Future<Result<void>> clear() async => const Result.ok(null);

  @override
  Future<Result<CreatedInvite>> createInvite(
      {PersonRole role = PersonRole.guest}) async {
    final result = await _api.createInvite(role: _wire(role));
    final made = result.valueOrNull;
    final code = made?.code;
    if (made == null || code == null) {
      return Result.err(result.failureOrNull ??
          const ServerFailure('The server made no invitation.'));
    }
    return Result.ok(CreatedInvite(
      id: made.id,
      url: joinLink(_address(), code).toString(),
      expiresAt: _time(made.expiresAtMs),
      role: _role(made.role),
    ));
  }

  @override
  Future<Result<List<InviteRow>>> invites() async {
    final result = await _api.invites();
    final list = result.valueOrNull;
    if (list == null) return Result.err(result.failureOrNull!);
    return Result.ok([
      for (final i in list)
        InviteRow(
          id: i.id,
          state: i.state,
          createdAt: _time(i.createdAtMs),
          expiresAt: _time(i.expiresAtMs),
          role: _role(i.role),
          redeemedBy: i.usedBy,
          redeemedAt: i.usedAtMs == null ? null : _time(i.usedAtMs!),
        ),
    ]);
  }

  @override
  Future<Result<void>> revokeInvite(String id) => _api.revokeInvite(id);

  @override
  Future<Result<List<PersonOnServer>>> people() async {
    final result = await _api.people();
    final list = result.valueOrNull;
    if (list == null) return Result.err(result.failureOrNull!);
    _ids
      ..clear()
      ..addEntries([for (final p in list) MapEntry(p.username, p.id)]);
    return Result.ok([
      for (final p in list)
        PersonOnServer(
          user: p.username,
          role: _role(p.role),
          isFounding: false,
          invitedBy: p.invitedBy,
          joinedAt: _time(p.createdAtMs),
        ),
    ]);
  }

  Future<String?> _idOf(String user) async {
    if (!_ids.containsKey(user)) await people();
    return _ids[user];
  }

  @override
  Future<Result<void>> setRole(String user, PersonRole role) async {
    final id = await _idOf(user);
    if (id == null) {
      return const Result.err(
          NotFoundFailure('There is nobody with that name.'));
    }
    return _api.updatePerson(id, role: _wire(role));
  }

  @override
  Future<Result<void>> removePerson(String user) async {
    final id = await _idOf(user);
    if (id == null) {
      return const Result.err(
          NotFoundFailure('There is nobody with that name.'));
    }
    return _api.removePerson(id);
  }
}
