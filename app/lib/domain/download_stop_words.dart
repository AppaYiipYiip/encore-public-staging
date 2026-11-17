/// Every English sentence of a download's Stop and of the question before it is removed (docs/design S-16, S-17, S-96; N-39), in ONE table.
///
/// Each sentence is ONE whole message with named parameters (a number is never glued to a fragment, a plural is chosen inside the sentence), so that
/// the day the app is localised (item N-41, Arabic) this table can be lifted into message files without anybody re-reading the code that calls it.
/// The words of the line under a download ("Stopped · 12 of 217 on this phone") are `describeDownload`'s, of the card "is stopped" are
/// `DownloadCardWords`'s: the same one phrasing, in the file that already owns it. The Arabic stays in the drawing.
///
/// Where the drawing gives no wording (no songs on the phone yet, or one song) the sentence is the same sentence in the plain form and is listed
/// as a question in the hand-back of the pull request.
class DownloadStopWords {
  const DownloadStopWords();

  String stop() => 'Stop';

  String resume() => 'Resume';

  // ----------------------------------------------------------------------------------------------------------------------- the sheet

  /// The small line of the Stop row: what is kept, and that the server goes on (Stop is the phone copy only).
  String stopKeeps({required int onPhone}) => onPhone == 0
      ? 'No songs are on this phone yet. Your server goes on saving the rest.'
      : onPhone == 1
          ? 'Keeps the song on this phone. Your server goes on saving the rest.'
          : 'Keeps the $onPhone songs on this phone. Your server goes on saving the rest.';

  String resumeCopies() => 'Copies the rest to this phone.';

  String removeDownload() => 'Remove download';

  String removeAsksFirst() =>
      'Takes this download off this phone. You are asked first.';

  String keepDownloaded() => 'Keep downloaded';

  // ------------------------------------------------------------------------------------------------------- the question before Remove

  String removeTitle({required String name}) => 'Remove $name from this phone?';

  /// What is deleted. A download that is finished has no "rest".
  String removeDeletes({
    required int onPhone,
    required String size,
    required bool finished,
  }) {
    if (onPhone == 0) {
      return finished
          ? 'No songs are on this phone.'
          : 'No songs are on this phone yet, and the rest will not be downloaded.';
    }
    final what = onPhone == 1
        ? 'The song on this phone ($size) is deleted'
        : 'The $onPhone songs on this phone ($size) are deleted';
    return finished ? '$what.' : '$what, and the rest will not be downloaded.';
  }

  /// What is kept, and that it can be downloaded again.
  String removeStays() =>
      'Your music stays on your server and you can download it again. A song that another download also has stays on this phone.';

  String cancel() => 'Cancel';

  String remove() => 'Remove';
}
