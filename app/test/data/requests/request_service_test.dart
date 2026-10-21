import 'package:drift/native.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/request_repository.dart';
import 'package:encore/data/requests/portal_client.dart';
import 'package:encore/data/requests/request_service.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeBackend implements RequestBackend {
  final List<String> calls = [];
  Result<RequestReceipt> next =
      const Result.ok(RequestReceipt(kind: 'album', name: 'Kodama'));

  @override
  Future<Result<RequestReceipt>> request(
      {required String artist, String? album}) async {
    calls.add('$artist|${album ?? ''}');
    return next;
  }

  @override
  Future<Result<PortalOverview>> overview() async =>
      const Result.ok(PortalOverview());

  @override
  Future<Result<String>> check() async => const Result.ok('marwa');
}

void main() {
  late AppDatabase db;
  late RequestRepository repo;
  late FakeBackend backend;
  late RequestService service;
  late int serverId;
  var configured = true;

  setUp(() async {
    configured = true;
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
        name: 'T', username: 'u', endpointsJson: '[]', createdAtMs: 0));
    repo = RequestRepository(db, serverId);
    backend = FakeBackend();
    service = RequestService(
      repository: repo,
      backend: () async => configured ? backend : null,
    );
  });

  tearDown(() => db.close());

  test('a successful request is stored as requested', () async {
    final outcome = await service.request(artist: 'Alcest', album: 'Kodama');
    expect(outcome, isA<RequestSent>());
    final row = (outcome as RequestSent).row;
    expect(row.state, RequestState.requested);
    expect(backend.calls, ['Alcest|Kodama']);
  });

  test('asking twice sends once', () async {
    await service.request(artist: 'Alcest', album: 'Kodama');
    final again = await service.request(artist: 'alcest', album: 'KODAMA');
    expect((again as RequestSent).wasDuplicate, isTrue);
    expect(backend.calls.length, 1);
  });

  test('not configured asks for setup and stores nothing', () async {
    configured = false;
    final outcome = await service.request(artist: 'Alcest');
    expect(outcome, isA<RequestNeedsSetup>());
    expect(await repo.watchAll().first, isEmpty);
  });

  test('a failure keeps the intent as failed and can be retried', () async {
    backend.next = const Result.err(NetworkFailure('Cannot reach'));
    final failed = await service.request(artist: 'Alcest', album: 'Kodama');
    expect(failed, isA<RequestFailed>());
    expect((failed as RequestFailed).row!.state, RequestState.failed);

    backend.next =
        const Result.ok(RequestReceipt(kind: 'album', name: 'Kodama'));
    final retry = await service.request(artist: 'Alcest', album: 'Kodama');
    expect((retry as RequestSent).row.state, RequestState.requested);
    expect((await repo.watchAll().first).length, 1, reason: 'same row reused');
  });

  test('an artist request sends no album', () async {
    await service.request(artist: 'Alcest');
    expect(backend.calls, ['Alcest|']);
  });
}
