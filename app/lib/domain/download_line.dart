import 'package:meta/meta.dart';

/// The line under a download's title, in ONE vocabulary for every place a person looks (the Library rows, the playlist and album headers,
/// Settings > Downloads & storage), drawn 5 Nov 2026 in `docs/design` S-16 "the two stages" and S-17 (P2-22 part 2, `docs/33` PB-34, PB-35, PB-37).
///
/// A download has two stages that overlap: the **server** gets the songs (it can take tens of minutes, paced to what YouTube allows) and the
/// **phone** takes them from the server. So the line says both numbers, the phone's first (it is what plays): "12 of 217 on this phone · 40 ready on
/// your server". When the phone cannot move, its reason replaces the server's half (one cause for the whole screen, and the server's counts are stale
/// then): "12 of 40 on this phone · waiting for Wi-Fi".
///
/// Pure Dart: the screens give it numbers, it gives back words and two bar lengths.

/// Why the phone cannot move now (one cause for the whole screen, the strip's own test).
enum PhoneWait {
  /// "Wi-Fi only" is on and the phone is on mobile data.
  wifi('waiting for Wi-Fi', 'Waiting for Wi-Fi'),

  /// No network, or the network gives no internet.
  connection('waiting for a connection', 'Waiting for a connection'),

  /// Internet is found but the person's server does not answer. A plain music server never gave this reason ([legacyWords] is null).
  server('waiting for your server', null),

  /// The storage limit the person set is reached: the downloads wait (the same words as the banner, `DownloadsPausedBanner`).
  limit('paused: your storage limit is reached', null),

  /// The phone is nearly full: downloads never take the last of it.
  space('paused: your phone is almost full', null);

  const PhoneWait(this.words, this.legacyWords);

  /// In the new line: "12 of 40 on this phone · waiting for Wi-Fi".
  final String words;

  /// In the line a plain music server has always had: "Waiting for Wi-Fi • 12 of 40".
  final String? legacyWords;
}

/// What the Encore server says about the songs of one download.
@immutable
class ServerStage {
  const ServerStage({
    required this.total,
    required this.ready,
    required this.keeping,
    required this.queued,
    required this.failed,
    this.retryable = 0,
    this.restingUntil,
  });

  final int total;

  /// The server holds the file.
  final int ready;
  final int keeping;
  final int queued;

  /// Not coming.
  final int failed;

  /// Of the failed, how many asking again can help.
  final int retryable;

  /// When YouTube lets the server go on, while it holds the server back; else `null`.
  final DateTime? restingUntil;

  /// On its way: being fetched or waiting.
  int get waiting => keeping + queued;

  bool get hasAll => total > 0 && ready >= total;
}

/// Everything the line is made of.
@immutable
class DownloadFacts {
  const DownloadFacts({
    required this.phoneDone,
    required this.phoneTotal,
    this.phoneActive = 0,
    this.phoneFailed = 0,
    this.confirmedEmpty = false,
    this.serverKeeps = false,
    this.server,
    this.wait,
  });

  /// Songs of this download that are on the phone / that it holds (the phone's own table).
  final int phoneDone;
  final int phoneTotal;

  /// Songs the phone is fetching or has queued, and those it could not take.
  final int phoneActive;
  final int phoneFailed;

  /// The download was counted and holds no songs (as against songs that have not reached the phone yet).
  final bool confirmedEmpty;

  /// The phone is on an Encore server that keeps songs (`keep` in its features): the lines of S-16. Otherwise the lines the app has always had.
  final bool serverKeeps;

  /// What the server says, when it has said (a phone that has just started, or whose server does not know this download, has none yet).
  final ServerStage? server;

  /// Why the phone cannot move, if it cannot.
  final PhoneWait? wait;
}

@immutable
class DownloadLine {
  const DownloadLine(
    this.text, {
    this.phoneFraction = 0,
    double? serverFraction,
    this.complete = false,
    this.failed = 0,
    this.canRetry = false,
    this.twoStages = false,
    this.stuck = false,
  }) : serverFraction = serverFraction ?? phoneFraction;

  /// The line itself.
  final String text;

  /// How much of the bar is filled (on the phone), 0..1.
  final double phoneFraction;

  /// How far the lighter tone goes (ready on the server), never less than [phoneFraction].
  final double serverFraction;

  /// Every song is on the phone.
  final bool complete;

  /// Songs that did not come (the server's and the phone's), for the row to name with Retry.
  final int failed;

  /// Asking again can help at least one of them.
  final bool canRetry;

  /// This is a line of the two stages (the server keeps the songs), as against the line a plain music server has always had: a screen draws the bar
  /// and the failures only for these.
  final bool twoStages;

  /// Nothing more is coming: every song that can come has, and some did not. A control must not go on saying "downloading".
  final bool stuck;
}

/// Why the phone could not take a song, in plain words. [recorded] is what the downloader wrote down (an exception class, a path, an HTTP status): it
/// is read to pick the sentence and is never shown.
String phoneFailureWords(String? recorded) {
  final raw = (recorded ?? '').toLowerCase();
  if (raw.contains('no longer on the server')) {
    return 'The server no longer has this song.';
  }
  if (raw.contains('space') || raw.contains('enospc')) {
    return 'There is no room on this phone.';
  }
  return 'Could not be saved on this phone.';
}

DownloadLine describeDownload(DownloadFacts f) =>
    f.serverKeeps ? _twoStages(f) : _legacy(f);

String _songs(int n) => n == 1 ? '1 song' : '$n songs';

String _clock(DateTime t) =>
    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

double _fraction(int part, int whole) =>
    whole <= 0 ? 0 : (part / whole).clamp(0.0, 1.0);

// ------------------------------------------------------------------------------------------------------------------ the lines of S-16

DownloadLine _twoStages(DownloadFacts f) {
  final s = f.server;
  final done = f.phoneDone;
  // The phone may not have the songs yet (their rows have not synced) while the server already counts them.
  final total = f.phoneTotal > 0 ? f.phoneTotal : (s?.total ?? 0);
  final phone = _fraction(done, total);
  final failed = (s?.failed ?? 0) + f.phoneFailed;
  final canRetry = (s?.retryable ?? 0) > 0 || f.phoneFailed > 0;
  final tone = s == null ? phone : _max(phone, _fraction(s.ready, s.total));

  DownloadLine say(String text,
          {double? server, bool complete = false, bool stuck = false}) =>
      DownloadLine(text,
          phoneFraction: phone,
          serverFraction: server ?? tone,
          complete: complete,
          failed: failed,
          canRetry: canRetry,
          twoStages: true,
          stuck: stuck);

  if (total > 0 && done >= total) {
    return DownloadLine('Downloaded • ${_songs(total)}',
        phoneFraction: 1, complete: true, twoStages: true);
  }
  if (f.phoneTotal == 0 && f.confirmedEmpty && (s == null || s.total == 0)) {
    // Not a stage of anything: the same words as ever, no bar.
    return const DownloadLine('Nothing to download yet');
  }

  // The phone's reason wins: the server's counts are stale while the phone cannot reach it, and one cause is told for the whole screen.
  final wait = f.wait;
  if (wait != null) {
    // What the server said about songs that did not come is as old as its counts: not told now, and no Retry that could not be sent.
    return DownloadLine('$done of $total on this phone · ${wait.words}',
        phoneFraction: phone, twoStages: true);
  }

  // Everything that can come has come, and some did not: say so (the row offers Retry when asking again can help). "Settled" is told by the
  // server's numbers: it has nothing on the way, and nothing it holds is waiting for the phone. The phone's own count of queued rows cannot tell:
  // it keeps a queued row for every song the server has not got (PB-35), for ever, so it would never be settled (found on a real server).
  // (a song the phone failed to take is not waiting for the phone: it waits for Retry)
  final settled = s == null
      ? f.phoneActive == 0
      : s.waiting == 0 && s.ready <= done + f.phoneFailed;
  if (failed > 0 && settled) {
    return say(
        done > 0
            ? '$done of $total on this phone · ${_songs(failed)} did not come'
            : '${_songs(failed)} did not come',
        stuck: true);
  }

  if (s == null) {
    return say(done > 0
        ? '$done of $total on this phone'
        : 'Getting ready to download');
  }

  final until = s.restingUntil;
  if (!s.hasAll && s.waiting > 0 && until != null) {
    return say(done > 0
        ? '$done of $total on this phone · your server is resting until ${_clock(until)}'
        : 'Your server is resting until ${_clock(until)} · ${s.ready} of ${s.total} ready');
  }

  if (s.hasAll) {
    return say('Downloading to this phone · $done of $total');
  }

  if (done == 0) {
    return say(s.ready == 0 && s.keeping == 0 && s.queued > 0
        ? 'Waiting its turn on your server'
        : 'Getting it on your server · ${s.ready} of ${s.total} ready');
  }
  return say('$done of $total on this phone · ${s.ready} ready on your server');
}

double _max(double a, double b) => a > b ? a : b;

// ------------------------------------------------------------------------------------------------------------------ the lines a plain music server has always had

DownloadLine _legacy(DownloadFacts f) {
  final done = f.phoneDone;
  final total = f.phoneTotal;
  final phone = _fraction(done, total);
  if (total == 0) {
    return DownloadLine(f.confirmedEmpty
        ? 'Nothing to download yet'
        : 'Getting ready to download');
  }
  if (done >= total) {
    return DownloadLine('Downloaded • ${_songs(total)}',
        phoneFraction: 1, complete: true);
  }
  if (f.phoneActive == 0 && f.phoneFailed > 0) {
    return DownloadLine('$done of $total downloaded • some did not come',
        phoneFraction: phone, failed: f.phoneFailed, canRetry: true);
  }
  if (done == 0 && f.phoneActive == 0) {
    return const DownloadLine('Getting ready to download');
  }
  final words = f.wait?.legacyWords;
  return DownloadLine(
      words == null
          ? 'Downloading $done of $total'
          : '$words • $done of $total',
      phoneFraction: phone);
}
