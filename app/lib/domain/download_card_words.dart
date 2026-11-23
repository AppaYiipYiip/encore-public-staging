/// Every English sentence of the download card (docs/design S-95, P2-29), in ONE table.
///
/// Each sentence is ONE whole message with named parameters: a number is never glued to a fragment ("and N more" takes the count, a plural is chosen
/// inside the sentence), so that the day the app is localised (the board item "The app speaks Arabic first") this table can be lifted into message files
/// mechanically, without anybody re-reading the code that calls it. Nothing outside this file writes a word of the card. The line under a download is
/// NOT here: it is S-16's own line, from `describeDownload` (`download_line.dart`), the one phrasing of how a download is going.
///
/// The Arabic of the same sentences stays in the drawing, as the fixture of that later item.
class DownloadCardWords {
  const DownloadCardWords();

  // ---------------------------------------------------------------------------------------------------------------- the running card

  String downloadingTitle({required String name}) => 'Downloading $name';

  String importingTitle({required String name}) => 'Importing $name';

  /// The first second after the person presses Download: the server has not answered yet.
  String starting() => 'Starting…';

  /// The import page's own words while the server looks the songs up (`importSummary` adds what was not found after them).
  String findingSongs({required int looked, required int total}) =>
      'Finding songs: $looked of $total';

  String severalTitle({required int count}) => '$count downloads';

  String severalBody({required int onPhone, required int total}) =>
      '$onPhone of $total songs on this phone';

  String andMore({required int count}) => 'and $count more';

  // ----------------------------------------------------------------------------------------------------- the card of the app closed

  /// Worded so that freezing leaves it TRUE: it says what was so, and when. It never says what is going on now.
  String stillSavingTitle({required String name}) =>
      '$name is still saving on your server';

  String readyAt({
    required int ready,
    required int total,
    required DateTime time,
  }) =>
      '$ready of $total were ready at ${_clock(time)}. Open Encore to see how far it is now.';

  // ------------------------------------------------------------------------------------------------------------------ a job is over

  String readyOfflineTitle({required String name}) => '$name is ready offline';

  String songsOnThisPhone({required int count}) => count == 1
      ? '1 song is on this phone.'
      : '$count songs are on this phone.';

  String didNotComeTitle({required String name, required int count}) =>
      count == 1
          ? '$name: 1 song did not come'
          : '$name: $count songs did not come';

  String didNotComeBody({required int onPhone, required int total}) =>
      '$onPhone of $total on this phone. Tap to see why.';

  String importReadyTitle({required String name}) => '“$name” is ready';

  String likedImportedTitle() => 'Your liked songs are imported';

  String songsInLibrary({required int added, required int total}) =>
      '$added of $total songs are in your library now.';

  String importStoppedTitle() => 'Import stopped';

  String importStoppedBody({required String name, required int kept}) => kept ==
          1
      ? '$name: 1 song stays in your library. The rest were not fetched.'
      : '$name: $kept songs stay in your library. The rest were not fetched.';

  // ------------------------------------------------------------------------------------------- a Download the person stopped (N-39)

  /// The card of a Download that the person stopped (S-95 "A download was stopped"). It is a pause that waits, so it says what is kept and that
  /// Resume continues; it names no clock time and no live count, so it stays true when it freezes.
  String downloadStoppedTitle({required String name}) => '$name is stopped';

  String downloadStoppedBody({required int onPhone, required int total}) =>
      onPhone == 1
          ? '1 of $total stays on this phone. Resume continues from there.'
          : '$onPhone of $total stay on this phone. Resume continues from there.';
}

/// "9:03", "21:05": the hour as it is, the minutes with two digits (the drawing's clock).
String _clock(DateTime t) => '${t.hour}:${t.minute.toString().padLeft(2, '0')}';
