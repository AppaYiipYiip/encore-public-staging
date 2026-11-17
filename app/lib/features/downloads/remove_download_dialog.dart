import 'package:flutter/material.dart';

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
Future<bool> confirmRemoveDownload(
  BuildContext context, {
  required String name,
  required PinState state,
}) async {
  final sure = await showDialog<bool>(
    context: context,
    builder: (dialog) {
      final c = dialog.colors;
      final finished = state.phase == PinPhase.complete;
      return AlertDialog(
        title: Text(_words.removeTitle(name: name)),
        scrollable: true,
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(_words.removeDeletes(
                onPhone: state.done,
                size: formatBytes(state.bytes),
                finished: finished)),
            const SizedBox(height: Space.sm),
            Text(_words.removeStays()),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(false),
            child: Text(_words.cancel()),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(true),
            child: Text(_words.remove(), style: TextStyle(color: c.danger)),
          ),
        ],
      );
    },
  );
  return sure == true;
}
