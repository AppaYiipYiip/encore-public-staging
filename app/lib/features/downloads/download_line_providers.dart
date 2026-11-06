import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meta/meta.dart';

import '../../app/providers.dart';
import '../../data/encore/encore_models.dart';
import '../../data/repos/downloads_repository.dart';
import '../../domain/download_line.dart';
import '../../domain/storage_guard.dart' show StorageVerdict;
import '../common/playability.dart' show serverAwayProvider;
import '../instant/release_save.dart' show releasePinStateProvider;
import '../settings/settings_controller.dart';
import 'download_providers.dart';
import 'keep_providers.dart';

/// Why the phone cannot move now, or `null` when it can: one cause for the whole screen (docs/design S-16 "waiting"), the same test the strip uses.
/// There is no connection; or "Wi-Fi only" is on and the phone is on mobile data; or internet is found but the person's server does not answer.
///
/// The server's silence is read from [serverAwayProvider] and nowhere else: the single lasting "can I reach my server" answer P1-15 built (B-17
/// counts eleven such notions in the app; this adds none).
final phoneWaitProvider = Provider<PhoneWait?>((ref) {
  final network = ref.watch(networkKindProvider).value ?? NetworkKind.wifi;
  if (network == NetworkKind.none) return PhoneWait.connection;
  final wifiOnly =
      ref.watch(settingsProvider.select((s) => s.wifiOnlyDownloads));
  if (wifiOnly && network != NetworkKind.wifi) return PhoneWait.wifi;
  if (ref.watch(serverAwayProvider)) return PhoneWait.server;
  // The queue is held back by the storage guard (the same verdict the banner in Settings shows).
  return switch (ref.watch(downloadVerdictProvider).value) {
    StorageVerdict.limitReached => PhoneWait.limit,
    StorageVerdict.lowSpace => PhoneWait.space,
    _ => null,
  };
});

/// What a download is, for the line under its title: something the person pinned (a playlist, the liked songs, an album, a song) or a catalogue
/// release (`cat:<id>`, whose songs the phone pinned one by one).
@immutable
class DownloadTarget {
  const DownloadTarget.pin(PinTargetType this.type, this.id)
      : releaseRefIds = const [];
  const DownloadTarget.release(this.id, this.releaseRefIds) : type = null;

  final PinTargetType? type;
  final String id;
  final List<String> releaseRefIds;

  bool get isRelease => type == null;

  /// The download as the server names it, or `null` for what the server does not keep on the person's behalf (an album or artist of the person's own
  /// music, a loose song).
  KeepGroupKey? get keepKey => switch (type) {
        null => KeepGroupKey('release', id, refs: releaseRefIds),
        PinTargetType.playlist => KeepGroupKey('playlist', id),
        PinTargetType.liked => const KeepGroupKey('liked', kLikedPinId),
        _ => null,
      };

  @override
  bool operator ==(Object other) =>
      other is DownloadTarget &&
      other.type == type &&
      other.id == id &&
      other.releaseRefIds.join(',') == releaseRefIds.join(',');

  @override
  int get hashCode => Object.hash(type, id, releaseRefIds.join(','));
}

/// The line under a download's title, the same on every screen: the phone's own table, what the server says about its stage, and why the phone waits.
/// On a plain music server it is exactly the line the app has always shown. `null` when the person has not downloaded this.
final downloadLineProvider =
    Provider.autoDispose.family<DownloadLine?, DownloadTarget>((ref, target) {
  final PinState phone = target.isRelease
      ? ref.watch(releasePinStateProvider(target.releaseRefIds.join(',')))
      : ref.watch(pinStateProvider((target.type!, target.id))).value ??
          PinState.none;
  if (!phone.pinned) return null;
  final keep = ref.watch(keepProvider);
  final key = target.keepKey;
  final group = key == null ? null : keep.of(key);
  return describeDownload(DownloadFacts(
    phoneDone: phone.done,
    phoneTotal: phone.total,
    phoneActive: phone.active,
    phoneFailed: phone.failed,
    confirmedEmpty: phone.confirmedEmpty,
    serverKeeps: keep.supported && key != null,
    wait: ref.watch(phoneWaitProvider),
    server: group == null
        ? null
        : ServerStage(
            total: group.total,
            ready: group.ready,
            keeping: group.keeping,
            queued: group.queued,
            failed: group.failed,
            retryable: group.retryable,
            restingUntil: keep.restingUntil,
          ),
  ));
});
