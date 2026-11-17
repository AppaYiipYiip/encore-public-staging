import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../downloads/download_notifications_prompt.dart';
import 'import_watch.dart';

/// What happens the moment an import has been started on an Encore server (docs/design S-95, P2-29): the card of the downloads follows it from now,
/// so the import watch reads the list at once (it would otherwise learn of it at its next look), and the phone's notification question is asked **once**
/// (D-52): at the first Import as at the first Download, our sentence first, never twice, and the import never waits for the answer.
void importStarted(BuildContext context, WidgetRef ref) {
  unawaited(ref.read(importWatchProvider.notifier).resync());
  unawaited(askAboutDownloadNotifications(context, ref));
}
