import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/repos/downloads_repository.dart';
import '../../design/tokens.dart';
import '../../domain/download_line.dart';
import '../../domain/download_stop_words.dart';
import '../downloads/download_line_providers.dart';
import '../downloads/download_notifications_prompt.dart';
import '../downloads/download_providers.dart';
import '../downloads/download_status.dart';
import '../downloads/remove_download_dialog.dart';
import 'encore_sheet.dart';
import 'format.dart';

/// Downloads whose button was pressed and whose answer has not come yet: the button shows "downloading" at once (owner, 7 Nov 2026: "pressing the
/// download button ... waits a second, then the download starts"; the pin and the first look at the songs take a moment, a press must not).
final _justPressedProvider =
    NotifierProvider.family<_JustPressed, bool, String>(_JustPressed.new);

class _JustPressed extends Notifier<bool> {
  _JustPressed(this.key);

  final String key;

  @override
  bool build() => false;

  void set(bool value) => state = value;
}

/// Spotify-style "Download" toggle for an album / playlist / liked songs.
///
/// States: outline arrow (off) -> progress ring (downloading) -> filled
/// accent circle (complete) -> warning (needs attention); a solid ring with a pause mark while the person's Stop holds the download (S-17, N-39).
/// Tapping an active toggle opens the download's sheet (S-96): Stop keeps the files, Remove asks before throwing them away.
class DownloadButton extends ConsumerWidget {
  const DownloadButton({
    super.key,
    required this.type,
    required this.targetId,
    required this.name,
    this.size = 34,
    this.stateOverride,
    this.onPin,
    this.onRemove,
    this.preparingLabel,
    this.target,
  });

  final PinTargetType type;
  final String targetId;

  /// Human name for messages ("Downloading Prog Snob").
  final String name;
  final double size;

  /// For a target the pins table does not know as one thing (a catalogue release on an Encore server: its songs' pins added up).
  final PinState? stateOverride;

  /// Replaces the plain pin; answers a sentence for the person when it could not be done (shown instead of "Downloading").
  final Future<String?> Function()? onPin;

  /// Replaces the plain unpin; answers a sentence to say instead of the usual "Removed ..." when something of it stayed (a song another
  /// downloaded release has too), or `null`.
  final Future<String?> Function()? onRemove;

  /// What the button says while the songs are not on the phone yet because the server is still getting them.
  final String? preparingLabel;

  /// The download as the line of the two stages names it, when it is not the plain pin of [type] and [targetId] (a catalogue release).
  final DownloadTarget? target;

  DownloadTarget get _target => target ?? DownloadTarget.pin(type, targetId);

  String get _pressKey => '${type.name}:$targetId';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fromPins = stateOverride ??
        ref.watch(pinStateProvider((type, targetId))).value ??
        PinState.none;
    final pressed = ref.watch(_justPressedProvider(_pressKey));
    // A press shows at once what the pin will show in a moment: the ring of a download that is starting.
    final state = pressed && fromPins.phase == PinPhase.off
        ? PinState(
            pinned: true,
            total: fromPins.total,
            done: 0,
            active: fromPins.total,
            failed: 0,
            bytes: 0,
            confirmedEmpty: false)
        : fromPins;
    final waiting = ref.watch(downloadsWaitProvider);
    final line = ref.watch(downloadLineProvider(_target));
    final c = context.colors;
    // Nothing more is coming and some songs did not: the control stops saying "downloading" (the lines under the title say which ones).
    final phase = line != null && line.twoStages && line.stuck
        ? PinPhase.attention
        : state.phase;

    final (IconData icon, Color fg, Color? fill, String label) =
        switch (phase) {
      PinPhase.off => (
          Icons.arrow_downward_rounded,
          c.onBgMuted,
          null,
          'Download $name',
        ),
      PinPhase.preparing || PinPhase.downloading => (
          Icons.arrow_downward_rounded,
          c.accent,
          null,
          phase == PinPhase.preparing && preparingLabel != null
              ? preparingLabel!
              : line != null && line.twoStages
                  // Both stages, in the words every screen uses (docs/design S-16): "12 of 217 on this phone · 40 ready on your server".
                  ? 'Downloading $name. ${line.text}'
                  : waiting == null
                      ? 'Downloading $name, ${(state.progress * 100).round()} percent'
                      : '$waiting to download $name',
        ),
      PinPhase.empty => (
          Icons.arrow_downward_rounded,
          c.accent,
          null,
          'Nothing to download yet. Songs you add to $name will download',
        ),
      PinPhase.stopped => (
          Icons.pause_rounded,
          c.accent,
          null,
          'Stopped. ${line != null && line.twoStages ? line.text : name}. Tap for options',
        ),
      PinPhase.complete => (
          Icons.arrow_downward_rounded,
          c.onAccent,
          c.accent,
          'Downloaded. Tap to remove $name from this phone',
        ),
      PinPhase.attention => (
          Icons.priority_high_rounded,
          c.onAccent,
          c.warning,
          line != null && line.stuck
              ? 'Some downloads failed. ${line.text}. Tap for options'
              : 'Some downloads failed. Tap for options',
        ),
    };

    final busy = phase == PinPhase.preparing || phase == PinPhase.downloading;

    return Semantics(
      button: true,
      label: label,
      excludeSemantics: true,
      child: InkResponse(
        radius: size,
        onTap: () => _onTap(context, ref, state),
        child: SizedBox.square(
          dimension: 48,
          child: Center(
            child: SizedBox.square(
              dimension: size,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  DecoratedBox(
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: fill,
                      border: fill == null
                          ? Border.all(
                              // The stopped download's ring is solid and in the accent: not the ring that turns, not the plain outline of
                              // "not downloaded" (the ring is what makes the pause mark the download's and not the player's).
                              color: phase == PinPhase.stopped
                                  ? c.accent
                                  : busy
                                      ? c.outline
                                      : c.onBgMuted,
                              width: phase == PinPhase.stopped ? 2.4 : 1.6,
                            )
                          : null,
                    ),
                    child: SizedBox.square(
                      dimension: size,
                      child: Icon(icon, size: size * 0.6, color: fg),
                    ),
                  ),
                  if (busy)
                    SizedBox.square(
                      dimension: size,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.4,
                        // Indeterminate until the first file lands.
                        value: state.done == 0 ? null : state.progress,
                        color: c.accent,
                        backgroundColor: Colors.transparent,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _onTap(
      BuildContext context, WidgetRef ref, PinState state) async {
    unawaited(HapticFeedback.selectionClick());
    final actions = ref.read(downloadActionsProvider);
    final messenger = ScaffoldMessenger.of(context);

    if (state.phase == PinPhase.off) {
      String? problem;
      final pressed = ref.read(_justPressedProvider(_pressKey).notifier);
      pressed.set(true);
      try {
        if (onPin != null) {
          problem = await onPin!();
        } else {
          await actions.pin(type, targetId);
        }
      } finally {
        // The pin (or the failure) is what the button shows from here on.
        pressed.set(false);
      }
      // Counted before the pin and found empty: say so, rather than promise a download that has nothing to fetch (Q1).
      final nothing = onPin == null &&
          stateOverride == null &&
          state.confirmedEmpty &&
          state.total == 0;
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(
          content: Text(problem ??
              (nothing
                  ? 'Nothing to download yet. Songs you add to $name will download.'
                  : 'Downloading $name for offline listening')),
        ));
      // The first Download asks, once, whether to show its progress (D-52). The download has already started and does not wait for the answer.
      if (problem == null && !nothing && context.mounted) {
        unawaited(askAboutDownloadNotifications(context, ref));
      }
      return;
    }

    final choice = await showEncoreSheet<_SheetChoice>(
      context: context,
      builder: (sheet) => _DownloadSheet(
          name: name,
          state: state,
          waiting: ref.read(downloadsWaitProvider),
          line: ref.read(downloadLineProvider(_target))),
    );
    switch (choice) {
      case _SheetChoice.remove:
        // Remove is the one thing that deletes, and it always asks first (S-96): Cancel changes nothing.
        if (!context.mounted) return;
        if (!await confirmRemoveDownload(context, name: name, state: state)) {
          return;
        }
        String? note;
        if (onRemove != null) {
          note = await onRemove!();
        } else {
          await actions.unpin(type, targetId);
        }
        messenger
          ..hideCurrentSnackBar()
          ..showSnackBar(
              SnackBar(content: Text(note ?? 'Removed $name from this phone')));
      case _SheetChoice.stop:
        // Keeps every file that is on the phone; no question (it deletes nothing and Resume undoes it).
        unawaited(ref.read(stopDownloadProvider)(_target));
      case _SheetChoice.resume:
        unawaited(ref.read(resumeDownloadProvider)(_target));
      case _SheetChoice.retry:
        // The server again for the songs it failed to get, and the phone again for the files it could not take.
        await ref.read(retryDownloadProvider)(_target);
      case null:
        break;
    }
  }
}

/// What a row of the sheet asks for.
enum _SheetChoice { retry, stop, resume, remove }

const DownloadStopWords _words = DownloadStopWords();

class _DownloadSheet extends StatelessWidget {
  const _DownloadSheet(
      {required this.name, required this.state, this.waiting, this.line});

  final String name;
  final PinState state;

  /// The line of the two stages, when the server keeps songs: it replaces the phone-only wording.
  final DownloadLine? line;

  /// Why nothing is moving ("Waiting for Wi-Fi"), when that is the case.
  final String? waiting;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final size = formatBytes(state.bytes);
    final stages = line != null && line!.twoStages && !line!.complete;
    final title = stages
        ? line!.text
        : switch (state.phase) {
            PinPhase.empty => 'Nothing to download yet',
            PinPhase.complete => 'Downloaded',
            PinPhase.attention => 'Some songs could not be downloaded',
            PinPhase.stopped => 'Stopped - ${state.done} of ${state.total}',
            _ => waiting == null
                ? 'Downloading ${state.done} of ${state.total}'
                : '$waiting - ${state.done} of ${state.total}',
          };
    // A stopped download sends no asks, so there is no "Try again now" until Resume (S-96 "stopped").
    final isStopped = state.phase == PinPhase.stopped;
    // Stop is offered while songs are coming (the line says so): not on a finished download, not on one with only songs that did not come, and not
    // on the line a plain music server has always had (no Stop is drawn for it).
    final canStop = !isStopped && line != null && line!.canStop;
    // Asking again is offered for what the phone could not take and for what the server could not get.
    final canTryAgain = !isStopped &&
        (state.phase == PinPhase.attention ||
            (line != null && line!.failed > 0 && line!.canRetry));
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
            Space.gutter, Space.lg, Space.gutter, Space.md),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(name,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: context.text.titleLarge),
            const SizedBox(height: Space.xs),
            Text(
              state.phase == PinPhase.empty
                  ? 'Songs you add will download by themselves.'
                  : '$title - ${plural(state.total, 'song')}'
                      '${state.bytes > 0 ? ', $size on this phone' : ''}',
              style: context.text.bodyMedium,
            ),
            const SizedBox(height: Space.lg),
            if (canTryAgain)
              ListTile(
                leading: const Icon(Icons.refresh_rounded),
                title: const Text('Try again now'),
                onTap: () => Navigator.of(context).pop(_SheetChoice.retry),
              ),
            if (canStop)
              ListTile(
                leading: const Icon(Icons.stop_circle_outlined),
                title: Text(_words.stop()),
                subtitle: Text(_words.stopKeeps(onPhone: state.done)),
                onTap: () => Navigator.of(context).pop(_SheetChoice.stop),
              ),
            if (isStopped)
              ListTile(
                leading: const Icon(Icons.play_circle_outline_rounded),
                title: Text(_words.resume()),
                subtitle: Text(_words.resumeCopies()),
                onTap: () => Navigator.of(context).pop(_SheetChoice.resume),
              ),
            ListTile(
              leading: Icon(Icons.delete_outline_rounded, color: c.danger),
              title: Text(_words.removeDownload(),
                  style: TextStyle(color: c.danger)),
              subtitle: Text(_words.removeAsksFirst()),
              onTap: () => Navigator.of(context).pop(_SheetChoice.remove),
            ),
            ListTile(
              leading: const Icon(Icons.close_rounded),
              title: Text(_words.keepDownloaded()),
              onTap: () => Navigator.of(context).pop(),
            ),
          ],
        ),
      ),
    );
  }
}
