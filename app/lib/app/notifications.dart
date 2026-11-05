import 'dart:async';

import 'package:background_downloader/background_downloader.dart' as downloader
    show FileDownloader, PermissionStatus, PermissionType;
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/logger.dart';
import '../data/alerts/alerts_service.dart';
import 'router.dart';

/// Android channel for "new music" alerts (the user can mute it in system
/// settings without touching the app).
const String kNewMusicChannelId = 'new_music';

/// The app's own notifications (new music, imports) - separate from the media
/// notification (`audio_service`) and the download progress notification
/// (`background_downloader`).
///
/// Works from the background sync job too: it initialises itself on first use
/// and needs nothing but the plugin. A notification is a convenience, so every
/// call swallows (and logs) platform trouble instead of failing its caller -
/// on a desktop test host the plugin has no platform at all.
class LocalNotifications implements AlertSink {
  LocalNotifications([FlutterLocalNotificationsPlugin? plugin])
      : _plugin = plugin ?? FlutterLocalNotificationsPlugin();

  final FlutterLocalNotificationsPlugin _plugin;
  bool _initialised = false;
  bool _available = true;
  void Function(String route)? _onOpen;

  /// Prepares the plugin. [onOpen] receives the in-app route of a tapped
  /// notification while the app is running.
  Future<void> init({void Function(String route)? onOpen}) async {
    if (onOpen != null) _onOpen = onOpen;
    if (_initialised) return;
    _initialised = true;
    try {
      await _plugin.initialize(
        settings: const InitializationSettings(
          android: AndroidInitializationSettings('ic_stat_encore'),
        ),
        onDidReceiveNotificationResponse: (response) {
          final route = response.payload;
          if (route != null && route.isNotEmpty) _onOpen?.call(route);
        },
      );
    } on Object catch (error) {
      _available = false;
      Log.warn('notify', 'notifications unavailable', error);
    }
  }

  /// The route of the notification that *started* the app, once.
  Future<String?> launchRoute() async {
    await init();
    if (!_available) return null;
    try {
      final details = await _plugin.getNotificationAppLaunchDetails();
      if (details?.didNotificationLaunchApp ?? false) {
        return details!.notificationResponse?.payload;
      }
    } on Object catch (error) {
      Log.debug('notify', 'launch details unavailable: $error');
    }
    return null;
  }

  /// Asks for the Android 13+ notification permission; `true` when granted
  /// (or not needed), `false` when refused or not possible.
  Future<bool> requestPermission() async {
    await init();
    if (!_available) return false;
    try {
      final android = _plugin.resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>();
      return await android?.requestNotificationsPermission() ?? true;
    } on Object catch (error) {
      Log.warn('notify', 'permission request failed', error);
      return false;
    }
  }

  /// Whether there is nothing to ask: `true` below Android 13 (no question exists there) and once the permission is granted; `false` on Android 13+
  /// while it is not granted. Asked of the downloader's own permission service (the one whose progress notification this is for), which answers
  /// "granted" below Android 13. When it cannot be known the answer is `true`: a question is never asked on a guess.
  Future<bool> areAllowed() async {
    try {
      final status = await downloader.FileDownloader()
          .permissions
          .status(downloader.PermissionType.notifications);
      return status != downloader.PermissionStatus.denied &&
          status != downloader.PermissionStatus.undetermined;
    } on Object catch (error) {
      Log.debug('notify', 'permission status unavailable: $error');
      return true;
    }
  }

  @override
  Future<void> show(AlertNotification notification) async {
    await init();
    if (!_available) return;
    try {
      await _plugin.show(
        id: notification.id,
        title: notification.title,
        body: notification.body,
        payload: notification.route,
        notificationDetails: NotificationDetails(
          android: AndroidNotificationDetails(
            kNewMusicChannelId,
            'New music',
            channelDescription:
                'Albums and releases from artists you play, and imports that '
                'have progressed.',
            importance: Importance.defaultImportance,
            priority: Priority.defaultPriority,
            icon: 'ic_stat_encore',
            category: AndroidNotificationCategory.recommendation,
            styleInformation: BigTextStyleInformation(notification.body),
          ),
        ),
      );
    } on Object catch (error) {
      Log.warn('notify', 'could not show a notification', error);
    }
  }
}

final localNotificationsProvider =
    Provider<LocalNotifications>((ref) => LocalNotifications());

const String _kAsked = 'encore.notificationsAsked';

/// Asks Android 13+ for the notification permission **once**, at the first
/// good moment (the first successful sync, so the question comes with a
/// working library behind it) and only if an alert is switched on. Without
/// this the new-music alerts would be silently dropped until the person
/// happened to toggle a switch.
Future<bool> askForNotificationsOnce(
  LocalNotifications notifications, {
  required bool anyAlertOn,
}) async {
  if (!anyAlertOn) return false;
  try {
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_kAsked) ?? false) return false;
    await prefs.setBool(_kAsked, true);
    await notifications.requestPermission();
    return true;
  } on Object catch (error) {
    Log.debug('notify', 'permission prompt skipped: $error');
    return false;
  }
}

/// The flag of the download-progress question: its own key, independent of the news-alert question's [_kAsked].
const String _kDownloadAsked = 'encore.downloadNotificationsAsked';

/// The one question about download progress (D-52, drawn as S-92): **once**, the first time the person presses Download, with our own sentence
/// first. Its own flag, independent of the news-alert question above: the two never use each other up.
///
/// * Nothing to ask (below Android 13, or already granted): `false`, and the flag is left alone.
/// * Otherwise the flag is set **before** anything is shown, so the question is used up even when the person says "Not now": never asked twice.
/// * [explain] shows our sentence and answers `true` for "Allow"; on "Not now" the phone's own question is not shown.
///
/// The download itself never waits for this: callers start it first and do not await the answer.
Future<bool> askForDownloadNotificationsOnce(
  LocalNotifications notifications, {
  required Future<bool> Function() explain,
}) async {
  try {
    if (await notifications.areAllowed()) return false;
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_kDownloadAsked) ?? false) return false;
    await prefs.setBool(_kDownloadAsked, true);
    if (!await explain()) return false;
    await notifications.requestPermission();
    return true;
  } on Object catch (error) {
    Log.debug('notify', 'download notification question skipped: $error');
    return false;
  }
}

/// Sends taps on a notification to the right screen, including the tap that
/// started the app. Watched once by the app widget.
final notificationRoutingProvider = Provider<void>((ref) {
  final notifications = ref.watch(localNotificationsProvider);
  final router = ref.watch(routerProvider);
  unawaited(() async {
    await notifications.init(onOpen: (route) => router.go(route));
    final launch = await notifications.launchRoute();
    if (launch != null && launch.isNotEmpty) router.go(launch);
  }());
});
