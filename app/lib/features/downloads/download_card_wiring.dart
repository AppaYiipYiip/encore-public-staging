import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_in_front.dart';
import '../../app/notifications.dart';
import '../../app/providers.dart' show clockProvider;
import 'download_card_jobs.dart';
import 'download_card_presenter.dart';

/// Where the card of the downloads goes: the phone's notifications. Tests replace it with a recorder.
final downloadCardSinkProvider = Provider<DownloadCardSink>(
  (ref) => ref.watch(localNotificationsProvider),
);

/// The least time between two posts of the card (the phone drops what comes faster).
final downloadCardPaceProvider =
    Provider<Duration>((ref) => const Duration(seconds: 1));

/// Feeds the one card of the downloads (docs/design S-95, P2-29): every change of the jobs, and every time the person leaves the app or comes back,
/// is a new look for the presenter, which decides what to post. Watched once by the app widget, like the download manager it reports on.
final downloadCardProvider = Provider<void>((ref) {
  final presenter = DownloadCardPresenter(
    sink: ref.watch(downloadCardSinkProvider),
    now: () => ref.read(clockProvider).now(),
    minGap: ref.watch(downloadCardPaceProvider),
  );
  ref.onDispose(presenter.dispose);

  void look() => unawaited(presenter.update(
        jobs: ref.read(downloadCardJobsProvider),
        foreground: ref.read(appInFrontProvider),
      ));

  ref.listen(downloadCardJobsProvider, (_, __) => look());
  ref.listen(appInFrontProvider, (_, __) => look());
  look();
});
