import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/repos/request_repository.dart';
import '../../data/requests/request_service.dart';
import '../../design/tokens.dart';
import '../settings/settings_controller.dart';
import 'download_service_sheet.dart';
import 'request_providers.dart';

/// Runs a request from the UI: sends it, and walks the user through the
/// one-time portal setup if none is configured yet.
Future<void> requestMusic(
  BuildContext context,
  WidgetRef ref, {
  required String artist,
  String? album,
}) async {
  final messenger = ScaffoldMessenger.of(context);
  final service = ref.read(requestServiceProvider);
  if (service == null) return;

  var outcome = await service.request(artist: artist, album: album);
  if (outcome is RequestNeedsSetup) {
    if (!context.mounted) return;
    final connected = await showDownloadServiceSheet(context);
    if (!connected) return;
    ref.invalidate(requestBackendProvider);
    outcome = await service.request(artist: artist, album: album);
  }

  final name = album ?? artist;
  switch (outcome) {
    case RequestSent(:final wasDuplicate):
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(
          content: Text(wasDuplicate
              ? '"$name" is already requested'
              : 'Requested "$name". It will appear in your library when it arrives.'),
        ));
    case RequestFailed(:final message):
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text("Couldn't request: $message")));
    case RequestNeedsSetup():
      break;
  }
}

/// Button that always shows the truth about one request.
class RequestChip extends ConsumerWidget {
  const RequestChip({super.key, required this.artist, this.album});

  final String artist;
  final String? album;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enabled =
        ref.watch(settingsProvider.select((s) => s.requestsEnabled));
    if (!enabled) return const SizedBox.shrink();
    final state = ref.watch(requestStateProvider((artist, album))).value;
    final c = context.colors;

    Widget chip({
      required String label,
      IconData? icon,
      VoidCallback? onTap,
      bool filled = false,
      Color? color,
      bool busy = false,
    }) {
      final fg = filled ? c.onAccent : (color ?? c.onBg);
      return Semantics(
        button: onTap != null,
        label: '$label: ${album ?? artist}',
        excludeSemantics: true,
        child: Material(
          color: filled ? c.accent : Colors.transparent,
          shape: StadiumBorder(
            side: filled
                ? BorderSide.none
                : BorderSide(color: color ?? c.outline, width: 1.2),
          ),
          child: InkWell(
            customBorder: const StadiumBorder(),
            onTap: onTap,
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 36, minWidth: 48),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (busy)
                      SizedBox.square(
                        dimension: 14,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: fg),
                      )
                    else if (icon != null)
                      Icon(icon, size: 16, color: fg),
                    if (busy || icon != null) const SizedBox(width: 6),
                    Text(label,
                        style: context.text.labelLarge?.copyWith(color: fg)),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    }

    void send() =>
        unawaited(requestMusic(context, ref, artist: artist, album: album));

    switch (state?.state) {
      case null:
        return chip(label: 'Request', icon: Icons.add_rounded, onTap: send);
      case RequestState.submitted:
        return chip(label: 'Sending', busy: true);
      case RequestState.requested:
        return chip(
          label: 'Requested',
          icon: Icons.check_rounded,
          color: c.accent,
        );
      case RequestState.inLibrary:
        return chip(
          label: 'In your library',
          icon: Icons.library_music_rounded,
          filled: true,
        );
      case RequestState.failed:
        return chip(
          label: 'Retry',
          icon: Icons.refresh_rounded,
          color: c.warning,
          onTap: send,
        );
      default:
        return chip(label: 'Request', icon: Icons.add_rounded, onTap: send);
    }
  }
}
