import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/notifications.dart';
import '../../design/tokens.dart';

/// The one question about download progress (D-52): asked **once**, the first time the person presses Download, with our own sentence first and
/// then the phone's own question. Drawn as S-92 "A permission is needed · notifications for download progress"
/// (`docs/design/directions/screens-first-run-and-settings.html`).
///
/// Call it **after** the download has been started and do not await it: the download never waits for the answer, and "Not now" or the phone's
/// "Don't allow" changes nothing about it. A phone below Android 13 has no such question, so nothing is shown there (see
/// [askForDownloadNotificationsOnce]).
///
/// The navigator is taken first, synchronously: the sheet or menu the person pressed Download in may close before the question is shown, and
/// its own context would be gone.
Future<void> askAboutDownloadNotifications(
    BuildContext context, WidgetRef ref) async {
  final navigator = Navigator.of(context, rootNavigator: true);
  final notifications = ref.read(localNotificationsProvider);
  await askForDownloadNotificationsOnce(notifications, explain: () async {
    if (!navigator.mounted) return false;
    final allow = await navigator.push<bool>(MaterialPageRoute<bool>(
      fullscreenDialog: true,
      builder: (_) => const DownloadNotificationsPage(),
    ));
    return allow ?? false;
  });
}

/// Our sentence, before the phone's own question (S-92). "Allow" answers `true`; "Not now" and going back answer `false`.
class DownloadNotificationsPage extends StatefulWidget {
  const DownloadNotificationsPage({super.key});

  static const String title = 'Show download progress?';
  static const String message =
      'While Encore downloads music it can show one notification with how far it has got. No news or alerts are sent unless you switch them on in Settings.';

  @override
  State<DownloadNotificationsPage> createState() =>
      _DownloadNotificationsPageState();
}

class _DownloadNotificationsPageState extends State<DownloadNotificationsPage> {
  @override
  void initState() {
    super.initState();
    // The Download button's own line ("Downloading ... for offline listening") is still on its way up from the bottom of the page behind this one;
    // the messenger would draw it over "Not now". The download itself is running and shows its progress on the button.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ScaffoldMessenger.of(context).hideCurrentSnackBar();
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        title: const Text('Download'),
      ),
      body: SafeArea(
        child: Padding(
          padding:
              const EdgeInsets.fromLTRB(Space.xl, Space.xl, Space.xl, Space.lg),
          child: Column(
            children: [
              Expanded(
                child: Center(
                  child: SingleChildScrollView(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        DecoratedBox(
                          decoration: BoxDecoration(
                              shape: BoxShape.circle, color: c.surfaceHigh),
                          child: SizedBox.square(
                            dimension: 96,
                            child: Icon(Icons.notifications_none_rounded,
                                size: 46, color: c.accent),
                          ),
                        ),
                        const SizedBox(height: Space.xl),
                        Semantics(
                          header: true,
                          child: Text(DownloadNotificationsPage.title,
                              style: context.text.titleLarge,
                              textAlign: TextAlign.center),
                        ),
                        const SizedBox(height: Space.md),
                        Text(DownloadNotificationsPage.message,
                            style: context.text.bodyMedium
                                ?.copyWith(color: c.onBgMuted, height: 1.4),
                            textAlign: TextAlign.center),
                      ],
                    ),
                  ),
                ),
              ),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () => Navigator.of(context).pop(true),
                  child: const Text('Allow'),
                ),
              ),
              const SizedBox(height: Space.sm),
              SizedBox(
                width: double.infinity,
                child: TextButton(
                  onPressed: () => Navigator.of(context).pop(false),
                  child: const Text('Not now'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
