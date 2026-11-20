import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show ProviderListenable;

import '../../data/repos/downloads_repository.dart';
import '../../design/tokens.dart';
import '../../domain/download_stop_words.dart';
import '../common/format.dart';

const DownloadStopWords _words = DownloadStopWords();

/// The question before a WHOLE download is turned off (docs/design S-96 "the question before a download is removed", N-39): asked at every door that
/// removes one (the Download button's sheet, the trash button on Settings > Downloads and storage), and answered `true` only by Remove. It says what
/// is deleted (the songs of this download that are on this phone, and how much room they take), what is kept (the music on the server, a song another
/// download also has) and that it can be downloaded again. Cancel changes nothing. The shape is S-05's and the existing "Remove all downloads?": Cancel
/// first, the verb in the danger colour on the right.
///
/// THE QUESTION MUST BE TRUE WHEN IT IS ANSWERED (review of PR 119): it reads the download through [state] while it is open, so songs that land
/// meanwhile are in it, and the removal that follows acts on the download as it is at the moment of the answer, whatever the numbers said. It is shown
/// on the root [navigator], taken by the caller BEFORE any sheet or await: the screen or button the person pressed may be gone by now (the page was
/// left while the sheet was open), and a choice made in the sheet must not vanish with it.
Future<bool> confirmRemoveDownload(
  NavigatorState navigator, {
  required String name,
  required ProviderListenable<PinState> state,
}) async {
  final overlay = navigator.overlay;
  if (!navigator.mounted || overlay == null || !overlay.mounted) return false;
  final sure = await showDialog<bool>(
    context: overlay.context,
    builder: (dialog) => _RemoveQuestion(name: name, state: state),
  );
  return sure == true;
}

class _RemoveQuestion extends ConsumerWidget {
  const _RemoveQuestion({required this.name, required this.state});

  final String name;
  final ProviderListenable<PinState> state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.colors;
    final now = ref.watch(state);
    final finished = now.phase == PinPhase.complete;
    return AlertDialog(
      title: Text(_words.removeTitle(name: name)),
      scrollable: true,
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_words.removeDeletes(
              onPhone: now.done,
              size: formatBytes(now.bytes),
              finished: finished)),
          const SizedBox(height: Space.sm),
          Text(_words.removeStays()),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(_words.cancel()),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: Text(_words.remove(), style: TextStyle(color: c.danger)),
        ),
      ],
    );
  }
}
