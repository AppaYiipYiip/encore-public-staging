import 'package:meta/meta.dart';

import 'download_card_words.dart';

/// The one notification of a download (docs/design S-95, P2-29): what a job is, what the card says while it runs, what the card of the app closed
/// says, and what is said when a job is over. Pure Dart: the numbers go in, words and a bar come out; `DownloadCardPresenter` decides when to post.
///
/// **Outside the app a card must stay true when it freezes.** The process can be killed any moment and nothing then refreshes the card, so the card
/// of the app closed ([datedCard]) says what WAS so and WHEN; a live reason ("resting until", "waiting for Wi-Fi") exists only in the live card, which
/// is shown only while the app is open.

/// Where a job stands. Only a [running] job is on the running card; a change from running to another phase makes one result card.
enum CardPhase {
  running,

  /// Everything is where it should be: every song on the phone (a download), every song found (an import).
  ready,

  /// Over, but some songs did not come.
  partly,

  /// An import somebody stopped (another device, or the server).
  stopped,
}

enum CardJobKind {
  /// Something the person downloaded: a playlist, an album, the liked songs, a catalogue release (two stages: the server, then the phone).
  download,

  /// An import with no Download of its playlist: one stage, the server's.
  import,
}

/// One download or import, as the card needs it.
@immutable
class CardJob {
  const CardJob({
    required this.key,
    required this.name,
    required this.text,
    required this.songs,
    this.kind = CardJobKind.download,
    this.onPhone = 0,
    this.ready = 0,
    this.inLibrary = 0,
    this.failed = 0,
    this.phase = CardPhase.running,
    this.starting = false,
    this.saving = false,
    this.importing = false,
    this.liked = false,
    this.progressDone = 0,
    this.progressOf = 0,
    this.importRoute,
    this.serverTotal,
  });

  /// Which job: the same download or import is the same key from one moment to the next (an import and the Download of its playlist are ONE job).
  final String key;
  final String name;

  /// The line under the job: S-16's line for a download, the import page's words while an import finds its songs.
  final String text;

  /// Songs of the job, songs of it on the phone, songs the server holds (never less than [onPhone] in [progressDone]).
  final int songs;
  final int onPhone;
  final int ready;

  /// Imports: the songs found, which are in the playlist (and so in the library).
  final int inLibrary;

  /// Songs that did not come.
  final int failed;

  final CardJobKind kind;
  final CardPhase phase;

  /// The first second: the server has not answered yet.
  final bool starting;

  /// The server still has songs of the job on their way: what the card of the app closed is about.
  final bool saving;

  /// The title says "Importing" (an import that is still finding or saving its songs) instead of "Downloading".
  final bool importing;

  /// An import of the person's liked songs (it makes no playlist).
  final bool liked;

  /// The job's share of the bar, in units (see [downloadBar], [importBar]).
  final int progressDone;
  final int progressOf;

  /// Where the card of an import that is over opens (the playlist it made).
  final String? importRoute;

  /// How many songs the server is going to hold when the job is not all of [songs] (an import: the songs it found, not the songs it was given),
  /// for "150 of 214 were ready"; `null` is [songs].
  final int? serverTotal;

  bool get running => phase == CardPhase.running;
}

/// Where the cards open: the list of what is downloaded, where every download has its line (S-16).
const String kDownloadsRoute = '/library/downloaded';

/// What the notification manager needs to show one card.
@immutable
class CardSpec {
  const CardSpec({
    required this.title,
    required this.body,
    this.expanded,
    this.progress,
    this.dated = false,
    this.route = kDownloadsRoute,
    this.stableKey,
  });

  final String title;
  final String body;

  /// The text of the card pulled open (several downloads), else `null`.
  final String? expanded;

  /// 0..1; `null` is a bar with no end yet (the card has just started) or no bar (the card of the app closed).
  final double? progress;

  /// The card of the app closed: it says when its numbers were true.
  final bool dated;
  final String route;

  /// What makes a card the same card although a clock in its words moved (the dated card names the time its numbers were true: a new minute is not
  /// a new card); `null` when the words are all there is to compare.
  final String? stableKey;

  /// What makes two cards the same card (the bar to 1 %): the notification manager is not asked again for a card that did not change.
  String get signature =>
      '${dated ? 'dated' : 'live'}\n${stableKey ?? '$title\n$body'}\n'
      '${expanded ?? ''}\n${progress == null ? '-' : (progress! * 100).floor()}';
}

/// The ids of the cards. The running card has ONE id for as long as the app runs, live or dated, so that coming back to the app replaces the dated
/// card in place instead of stacking a second one; a job that is over has an id of its own.
const int kRunningCardId = 7410;
const int _kResultCardIdBase = 7500;

/// Two jobs can land on the same one of the 500 ids, and the later result card then replaces the earlier one: a card is missing, never data lost;
/// accepted for that reason (a result card is a convenience, the job's own line in Downloaded stays).
int resultCardId(String key) {
  // FNV-1a: the same job is the same id in every run of the app, so that a card of it is replaced, not repeated.
  var hash = 0x811c9dc5;
  for (final unit in key.codeUnits) {
    hash = ((hash ^ unit) * 0x01000193) & 0x7fffffff;
  }
  return _kResultCardIdBase + hash % 500;
}

enum CardKind { running, result }

/// One call to the notification manager.
@immutable
class CardPost {
  const CardPost({
    required this.id,
    required this.kind,
    required this.spec,
    this.timeoutAfter,
  });

  final int id;
  final CardKind kind;
  final CardSpec spec;

  /// A live card is posted with a time to live: when the app is killed nothing refreshes it, and it goes away by itself instead of showing numbers
  /// that stopped being true. The dated card has none (it says when its numbers were true); a result card has none (the person swipes it away).
  final Duration? timeoutAfter;
}

/// The notification manager, as the card needs it. Implemented by `LocalNotifications`; tests replace it with a recorder.
abstract interface class DownloadCardSink {
  /// Whether anything may be shown (the phone's permission). Nothing is posted without it.
  Future<bool> canPost();

  Future<void> post(CardPost card);

  Future<void> cancel(int id);
}

/// A card for a job that is over: one per job, quiet, swiped away by the person.
@immutable
class CardResult {
  const CardResult({
    required this.key,
    required this.title,
    required this.body,
    required this.route,
  });

  final String key;
  final String title;
  final String body;
  final String route;
}

// ------------------------------------------------------------------------------------------------------------------------------ the bar

/// A download's share of its bar: each song is worth two units, one when the server holds it and one more when it is on the phone, so "a song on the
/// phone and a song ready on the server count the same", the bar moves from the first song on the server, does not jump when the first song reaches
/// the phone, and is full only when every song is on the phone (never "finished" early, docs/33 PB-38).
({int done, int of}) downloadBar({
  required int songs,
  required int onPhone,
  required int ready,
}) {
  final held = ready < onPhone ? onPhone : ready;
  return (done: onPhone + (held > songs ? songs : held), of: 2 * songs);
}

/// An import's share: finding the songs, then the server keeping them. A song not found needs no keeping.
({int done, int of}) importBar({
  required int total,
  required int matched,
  required int unmatched,
  required int kept,
}) {
  final looked = matched + unmatched;
  final saved = (kept > matched ? matched : kept) + unmatched;
  return (done: looked + saved, of: 2 * total);
}

/// The bar of the running card: the share of EVERYTHING the card has followed since it started, and **it only moves forward for as long as the card
/// lives**, with no qualifier (the owner's rule for S-95).
///
/// * A job that **ends** keeps its share in the total (its last numbers), so the card that goes on with the others does not restart from their own
///   share: job A finished at 100 % and job B at 10 % are 55 %, and when A ends the bar still says 55 %, not 10 %.
/// * A job that **joins** makes the whole bigger and the raw share smaller: the bar holds where it was and moves again once the bigger whole passes it
///   (the cost, said in docs/33 PB-43: with one job left the bar can sit above that job's own line).
/// * Only jobs that **ran while the card was live** are part of it: a download that finished long ago is on the list with a full share and must not
///   lift a bar it was never part of. A job that was running and is no longer on the list (the person removed it) keeps its last share too.
/// * A look at which **nothing that is left has a size yet** (every running job is `starting`, the server has not answered) does not advance the
///   bar: the jobs that ended would read as 100 % and the floor would keep that for the rest of the card.
/// * The card **ends** when no job runs: the next card starts from zero.
///
/// Fed with every look at the jobs, the app in front or not (a job that ends while the app is left must still be counted).
class CardBar {
  final Map<String, ({int done, int of})> _shares = {};
  double _floor = 0;

  /// What the bar says now: 0 before anything has run.
  double get value => _floor;

  /// Looks at the jobs once and returns [value].
  double apply(Iterable<CardJob> jobs) {
    final list = jobs.toList();
    if (!list.any((j) => j.running)) {
      _shares.clear();
      _floor = 0;
      return 0;
    }
    for (final j in list) {
      if (j.running || _shares.containsKey(j.key)) {
        _shares[j.key] = (done: j.progressDone, of: j.progressOf);
      }
    }
    if (!list.where((j) => j.running).every((j) => j.starting)) {
      var done = 0;
      var of = 0;
      for (final share in _shares.values) {
        done += share.done;
        of += share.of;
      }
      final raw = of <= 0 ? 0.0 : (done / of).clamp(0.0, 1.0);
      if (raw > _floor) _floor = raw;
    }
    return _floor;
  }
}

double _share(Iterable<CardJob> jobs) {
  var done = 0;
  var of = 0;
  for (final j in jobs) {
    done += j.progressDone;
    of += j.progressOf;
  }
  return of <= 0 ? 0 : (done / of).clamp(0.0, 1.0);
}

// ------------------------------------------------------------------------------------------------------------------------ the live card

/// How many downloads the expanded card names before "and N more".
const int kNamedOnCard = 3;

/// The card while the app is open: S-16's line for one job; for several, how many and what is on the phone, and pulled open a line each.
/// `null` when nothing runs. Its `progress` is the raw share of the jobs that run, `null` while all of them are starting; the bar that is SHOWN is
/// [CardBar]'s (it keeps what finished jobs were worth and never goes back), which `DownloadCardPresenter` puts in its place.
CardSpec? liveCard(List<CardJob> jobs, DownloadCardWords words) {
  final running = [
    for (final j in jobs)
      if (j.running) j
  ];
  if (running.isEmpty) return null;
  final starting = running.every((j) => j.starting);
  final progress = starting ? null : _share(running);
  if (running.length == 1) {
    final job = running.single;
    return CardSpec(
      title: job.importing
          ? words.importingTitle(name: job.name)
          : words.downloadingTitle(name: job.name),
      body: job.starting ? words.starting() : job.text,
      progress: progress,
      route: kDownloadsRoute,
    );
  }
  var onPhone = 0;
  var songs = 0;
  for (final j in running) {
    onPhone += j.onPhone;
    songs += j.songs;
  }
  final lines = <String>[
    for (final j in running.take(kNamedOnCard)) ...[
      j.name,
      j.starting ? words.starting() : j.text,
    ],
    if (running.length > kNamedOnCard)
      words.andMore(count: running.length - kNamedOnCard),
  ];
  return CardSpec(
    title: words.severalTitle(count: running.length),
    body: words.severalBody(onPhone: onPhone, total: songs),
    expanded: lines.join('\n'),
    progress: progress,
  );
}

// ----------------------------------------------------------------------------------------------------------------------- the dated card

/// The card once the person has left the app: what the server had ready, and when. No bar, no reason, no count of what is on the phone: all of that
/// is what a later moment makes false. A job the server has finished with has nothing to say here (the phone's copy of it runs only while the app
/// lives, and its end, when it comes, is a result card). `null` when no job is still being saved on the server.
CardSpec? datedCard(List<CardJob> jobs, DateTime now, DownloadCardWords words) {
  final saving = [
    for (final j in jobs)
      if (j.running && j.saving) j
  ];
  if (saving.isEmpty) return null;
  var ready = 0;
  var songs = 0;
  for (final j in saving) {
    ready += j.ready < j.onPhone ? j.onPhone : j.ready;
    songs += j.serverTotal ?? j.songs;
  }
  return CardSpec(
    title: saving.length == 1
        ? words.stillSavingTitle(name: saving.single.name)
        : words.severalTitle(count: saving.length),
    body: words.readyAt(ready: ready, total: songs, time: now),
    dated: true,
    stableKey: '${saving.map((j) => j.key).join(',')}|$ready|$songs',
  );
}

// ---------------------------------------------------------------------------------------------------------------------------- results

/// The cards for what ended between two looks at the jobs: a job that was running and is now over. A job that was already over, one that is no
/// longer there (the person removed it) and a single song make none.
List<CardResult> resultsBetween(
  List<CardJob> before,
  List<CardJob> after,
  DownloadCardWords words,
) {
  final was = {
    for (final j in before)
      if (j.running) j.key: j
  };
  final results = <CardResult>[];
  for (final job in after) {
    if (job.running || !was.containsKey(job.key)) continue;
    final result = _resultOf(job, words);
    if (result != null) results.add(result);
  }
  return results;
}

CardResult? _resultOf(CardJob job, DownloadCardWords words) {
  final isImport = job.kind == CardJobKind.import;
  switch (job.phase) {
    case CardPhase.running:
      return null;
    case CardPhase.ready:
      if (isImport) {
        return CardResult(
          key: job.key,
          title: job.liked
              ? words.likedImportedTitle()
              : words.importReadyTitle(name: job.name),
          body: words.songsInLibrary(added: job.inLibrary, total: job.songs),
          route: job.importRoute ?? '/settings/import',
        );
      }
      return CardResult(
        key: job.key,
        title: words.readyOfflineTitle(name: job.name),
        body: words.songsOnThisPhone(count: job.onPhone),
        route: kDownloadsRoute,
      );
    case CardPhase.partly:
      return CardResult(
        key: job.key,
        title: words.didNotComeTitle(name: job.name, count: job.failed),
        body: words.didNotComeBody(onPhone: job.onPhone, total: job.songs),
        route: kDownloadsRoute,
      );
    case CardPhase.stopped:
      return CardResult(
        key: job.key,
        title: words.importStoppedTitle(),
        body: words.importStoppedBody(name: job.name, kept: job.inLibrary),
        route: job.importRoute ?? '/settings/import',
      );
  }
}
