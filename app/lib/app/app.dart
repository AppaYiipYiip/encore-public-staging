import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/perf_overlay.dart';
import '../design/scroll_behavior.dart';
import '../design/theme.dart';
import '../design/tokens.dart';
import '../domain/invite_link.dart';
import '../features/auth/login_problem.dart';
import '../features/downloads/download_providers.dart';
import '../features/downloads/lyrics_for_downloads.dart';
import '../features/import/import_providers.dart';
import '../features/jam/jam_providers.dart';
import '../features/jam/jam_wiring.dart';
import '../features/people/people_providers.dart';
import '../features/player/lyrics_prefetch.dart';
import '../features/player/pending_likes.dart';
import '../features/providers.dart';
import '../features/requests/request_providers.dart';
import '../features/settings/settings_controller.dart';
import 'alerts_wiring.dart';
import 'background_sync.dart';
import 'branding.dart';
import 'cover_wiring.dart';
import 'notifications.dart';
import 'playback_providers.dart';
import 'power_wiring.dart';
import 'providers.dart';
import 'router.dart';
import 'session.dart';
import 'share_intake.dart';

/// Lets app-level events (a request arrived) show a message from anywhere.
final GlobalKey<ScaffoldMessengerState> _messengerKey =
    GlobalKey<ScaffoldMessengerState>();

class EncoreApp extends ConsumerWidget {
  const EncoreApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    final router = ref.watch(routerProvider);
    // Keeps lyrics for the current and next track warm in the cache.
    ref.watch(lyricsPrefetchProvider);
    // Downloaded songs bring their lyrics along (works offline afterwards).
    ref.watch(lyricsForDownloadsProvider);
    // The covers of what the person is likely to see are fetched in the background: offline shows covers, not letters.
    ref.watch(coverPrefetchProvider);
    // Keeps pinned music in step with the server (starts after start-up).
    ref.watch(downloadManagerProvider);
    // The periodic background job follows the setting.
    ref.watch(backgroundSyncApplyProvider);
    // A tapped notification opens the right screen (also when it started
    // the app).
    ref.watch(notificationRoutingProvider);
    // Battery level at both ends of every stretch of listening (Diagnostics).
    ref.watch(listeningLoggerProvider);
    // The saved equaliser curve is applied at start-up, not when its screen opens.
    ref.watch(equalizerServiceProvider);
    // Friends see what is playing, but only if this person chose to share it.
    ref.watch(activityPublisherProvider);
    // A song that cannot be played, or playback that stopped, is shown.
    ref.listen(playbackNoticesProvider, (_, next) {
      final notice = next.value;
      if (notice == null) return;
      _messengerKey.currentState
        ?..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(notice.message)));
    });
    // A like that could not be delivered (the song never reached the library):
    // said wherever the person is, once.
    ref.listen(pendingLikesProvider.select((s) => s.failedMessage),
        (_, message) {
      if (message == null) return;
      _messengerKey.currentState
        ?..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(message)));
      ref.read(pendingLikesProvider.notifier).failureShown();
    });
    // A Jam: this phone plays when it is the speaker, and what the Jam wants
    // the person to read (a refusal, "the Jam is over") is shown wherever they are.
    ref.watch(jamSpeakerProvider);
    ref.listen(jamControllerProvider.select((s) => s.message), (_, message) {
      if (message == null) return;
      _messengerKey.currentState
        ?..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(message)));
      ref.read(jamControllerProvider.notifier).dismissMessage();
    });
    // Whatever arrived while the app is open is on Home already: do not
    // announce it later.
    ref.listen(syncStatusProvider, (previous, next) {
      final before = previous?.value?.lastSuccessAt;
      final after = next.value?.lastSuccessAt;
      if (after == null || after == before) return;
      unawaited(ref.read(alertsServiceProvider)?.markSeen() ?? Future.value());
      final s = ref.read(settingsProvider);
      unawaited(askForNotificationsOnce(
        ref.read(localNotificationsProvider),
        anyAlertOn: s.alertsOnServer || s.alertsReleases || s.alertsImports,
      ));
    });
    // The server's imports are asked about as soon as the app starts (also what
    // lets a restarted server carry on in this person's name) and kept in step.
    ref.listen(importsProvider, (_, __) {});
    // A link shared from Spotify / YouTube Music opens the import page with
    // the link already in it.
    ref.listen(sharedTextProvider, (_, next) {
      final text = next.value?.text;
      if (text == null || text.trim().isEmpty) return;
      // An invitation to a server (a link tapped in a message, or shared to
      // the app) opens the app's own sign-up (docs/39 F3). Somebody who
      // already has an account here is told so, not sent to the import page.
      final invite = findInviteLink(text);
      if (invite != null) {
        unawaited(() async {
          // The account is read from the phone's own database: a link that
          // started the app arrives before that has answered.
          final server = await ref.read(activeServerProvider.future);
          if (server == null) {
            router.go('/join', extra: invite);
            return;
          }
          // After the first frame: there may be no screen to show it on yet.
          WidgetsBinding.instance.addPostFrameCallback((_) {
            _messengerKey.currentState
              ?..hideCurrentSnackBar()
              ..showSnackBar(const SnackBar(
                content: Text('That is an invitation to join a server, and '
                    'you already have an account here.'),
              ));
          });
        }());
        return;
      }
      unawaited(router.push<void>('/settings/import', extra: text));
    });
    // Requested music that has reached the library is announced once.
    ref.listen(requestArrivalsProvider, (_, next) {
      final arrived = next.value;
      if (arrived == null || arrived.isEmpty) return;
      final names = [for (final r in arrived) '"${r.title}"'];
      final text = names.length == 1
          ? '${names.first} is now in your library'
          : '${names.length} requested items are now in your library';
      _messengerKey.currentState
        ?..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(text)));
    });

    final dark = buildEncoreTheme(
      EncoreColors.dark(amoled: settings.amoledBlack),
      brightness: Brightness.dark,
    );
    final light =
        buildEncoreTheme(EncoreColors.light(), brightness: Brightness.light);

    return _SessionLifecycle(
      child: MaterialApp.router(
        title: AppBranding.name,
        debugShowCheckedModeBanner: false,
        scaffoldMessengerKey: _messengerKey,
        scrollBehavior: const EncoreScrollBehavior(),
        themeMode: settings.themeMode,
        theme: light,
        darkTheme: dark,
        routerConfig: router,
        // System bars follow the theme, in 3-button *and* gesture navigation
        // (FB-006): transparent status bar, nav bar painted like the app
        // background so no light strip appears under a dark UI.
        builder: (context, child) {
          final theme = Theme.of(context);
          final dark = theme.brightness == Brightness.dark;
          final bg = theme.extension<EncoreColors>()?.bg ??
              theme.scaffoldBackgroundColor;
          return AnnotatedRegion<SystemUiOverlayStyle>(
            value: SystemUiOverlayStyle(
              statusBarColor: Colors.transparent,
              statusBarIconBrightness:
                  dark ? Brightness.light : Brightness.dark,
              statusBarBrightness: dark ? Brightness.dark : Brightness.light,
              systemNavigationBarColor: bg,
              systemNavigationBarDividerColor: Colors.transparent,
              systemNavigationBarIconBrightness:
                  dark ? Brightness.light : Brightness.dark,
              systemNavigationBarContrastEnforced: false,
            ),
            child: settings.perfOverlay
                ? Stack(
                    children: [
                      child ?? const SizedBox.shrink(),
                      const PerfOverlay(),
                    ],
                  )
                : (child ?? const SizedBox.shrink()),
          );
        },
      ),
    );
  }
}

/// Connects Flutter lifecycle, connectivity and the session's scheduler.
class _SessionLifecycle extends ConsumerStatefulWidget {
  const _SessionLifecycle({required this.child});

  final Widget child;

  @override
  ConsumerState<_SessionLifecycle> createState() => _SessionLifecycleState();
}

class _SessionLifecycleState extends ConsumerState<_SessionLifecycle>
    with WidgetsBindingObserver {
  ServerSession? _started;
  late final GoRouter _router;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Opening a screen is a good moment to ask "is it current?" (ADR-071).
    _router = ref.read(routerProvider);
    _router.routerDelegate.addListener(_onNavigated);
  }

  @override
  void dispose() {
    _router.routerDelegate.removeListener(_onNavigated);
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  void _onNavigated() => ref.read(sessionProvider).value?.scheduler.poke();

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final session = ref.read(sessionProvider).value;
    if (session == null) return;
    switch (state) {
      case AppLifecycleState.resumed:
        session.onForeground();
      case AppLifecycleState.paused:
      case AppLifecycleState.hidden:
        session.onBackground();
      case AppLifecycleState.inactive:
      case AppLifecycleState.detached:
        break;
    }
  }

  Future<void> _attach(ServerSession session) async {
    if (identical(_started, session)) return;
    _started = session;
    session.scheduler
        .setMetered(ref.read(networkKindProvider).value == NetworkKind.mobile);

    // First frame is already on screen: start the network side now.
    unawaited(session.start());
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(sessionProvider, (_, next) {
      final session = next.value;
      if (session != null) unawaited(_attach(session));
    });
    // Something the person did was refused because the login stopped working: the prompt opens (P2-18).
    ref.listen(loginProblemProvider.select((s) => s.prompts), (previous, next) {
      if (next > (previous ?? 0)) {
        unawaited(ref.read(routerProvider).push('/sign-in-again'));
      }
    });
    // Mobile data is probed less often than Wi-Fi.
    ref.listen(networkKindProvider, (_, next) {
      ref
          .read(sessionProvider)
          .value
          ?.scheduler
          .setMetered(next.value == NetworkKind.mobile);
    });
    ref.listen(connectivityProvider, (_, next) {
      final online = next.value;
      final session = ref.read(sessionProvider).value;
      if (online != null && session != null) {
        session.scheduler.onConnectivityChanged(online: online);
      }
    });
    // The session may already be built by the time this widget builds.
    final current = ref.read(sessionProvider).value;
    if (current != null && !identical(_started, current)) {
      WidgetsBinding.instance
          .addPostFrameCallback((_) => unawaited(_attach(current)));
    }
    return widget.child;
  }
}
