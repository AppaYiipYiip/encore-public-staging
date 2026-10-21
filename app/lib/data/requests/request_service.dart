import '../../core/logger.dart';
import '../db/app_database.dart';
import '../repos/request_repository.dart';
import 'portal_client.dart';

/// Result of pressing "Request".
sealed class RequestOutcome {
  const RequestOutcome();
}

/// Sent (or already sent earlier - duplicates are suppressed).
final class RequestSent extends RequestOutcome {
  const RequestSent(this.row, {this.wasDuplicate = false});

  final RequestRow row;
  final bool wasDuplicate;
}

/// No download service configured yet: the UI offers the one-time setup.
final class RequestNeedsSetup extends RequestOutcome {
  const RequestNeedsSetup();
}

final class RequestFailed extends RequestOutcome {
  const RequestFailed(this.message, {this.row});

  final String message;
  final RequestRow? row;
}

/// Records the request locally *first* (so it survives crashes and shows up
/// instantly), then hands it to the portal. Failure keeps the row as `failed`
/// so the button can offer "Retry" instead of losing the intent.
class RequestService {
  RequestService({
    required RequestRepository repository,
    required Future<RequestBackend?> Function() backend,
  })  : _repo = repository,
        _backend = backend;

  final RequestRepository _repo;
  final Future<RequestBackend?> Function() _backend;

  Future<RequestOutcome> request({
    required String artist,
    String? album,
  }) async {
    final backend = await _backend();
    if (backend == null) return const RequestNeedsSetup();

    final existing = await _repo.find(artist, album);
    if (existing != null &&
        (existing.state == RequestState.requested ||
            existing.state == RequestState.inLibrary)) {
      return RequestSent(existing, wasDuplicate: true);
    }

    final row = await _repo.create(artist: artist, album: album);
    final result = await backend.request(artist: artist, album: album);
    return result.when(
      ok: (receipt) async {
        await _repo.setState(row.id, RequestState.requested,
            detail: receipt.name);
        final updated = await _repo.find(artist, album);
        return RequestSent(updated ?? row);
      },
      err: (failure) async {
        Log.warn('request', 'request failed: ${failure.message}');
        await _repo.setState(row.id, RequestState.failed,
            detail: failure.message);
        final updated = await _repo.find(artist, album);
        return RequestFailed(failure.message, row: updated ?? row);
      },
    );
  }
}
