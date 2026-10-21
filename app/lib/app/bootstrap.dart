import 'dart:async';

import 'package:audio_service/audio_service.dart';
import 'package:audio_session/audio_session.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/image_cache.dart';
import '../core/logger.dart';
import '../core/perf.dart';
import '../data/auth/credential_store.dart';
import '../data/db/open_database.dart';
import '../design/tokens.dart';
import '../features/settings/settings_controller.dart';
import '../playback/encore_audio_handler.dart';
import '../playback/just_audio_backend.dart';
import 'app.dart';
import 'branding.dart';
import 'playback_providers.dart';
import 'providers.dart';

/// App entry. Order is deliberate (R-03, startup budget):
///
/// 1. open the local database (background isolate) - no network
/// 2. `runApp` immediately; Home renders from the DB
/// 3. the media session starts in the background (`AudioService.init`) and the
///    playback engine is built once the server id is known
/// 4. the network session starts after the first frame (see `EncoreApp`)
Future<void> bootstrap() async {
  WidgetsFlutterBinding.ensureInitialized();
  final perf = PerfMonitor.instance..start();
  perf.begin('app.bootstrap->firstFrame');
  WidgetsBinding.instance.addPostFrameCallback((_) {
    perf.end('app.bootstrap->firstFrame');
  });

  FlutterError.onError = (details) {
    Log.error('flutter', details.exceptionAsString(), null, details.stack);
    FlutterError.presentError(details);
  };
  PlatformDispatcher.instance.onError = (error, stack) {
    Log.error('platform', 'Unhandled error', error, stack);
    return true;
  };

  ImageCacheConfig.configure();

  // The saved settings, before the first frame: the right theme from frame one,
  // and "private listening" already on for music that starts at once (B17).
  // A few milliseconds, measured by the span below; failing to read them only
  // means the defaults and the older async load.
  perf.begin('settings.preload');
  AppSettings? settings;
  try {
    settings =
        SettingsController.fromPrefs(await SharedPreferences.getInstance());
  } on PlatformException catch (error) {
    Log.warn('settings', 'preferences could not be read at start-up', error);
  }
  perf.end('settings.preload');

  final db = openAppDatabase();
  unawaited(_configureAudioSession());
  final backend = JustAudioBackend();
  final handler = _initAudioService();

  runApp(
    ProviderScope(
      // Riverpod 3 retries failing providers by default; our providers surface
      // failures themselves, and silent retry loops would hide them.
      retry: (retryCount, error) => null,
      overrides: [
        initialSettingsProvider.overrideWithValue(settings),
        databaseProvider.overrideWithValue(db),
        credentialStoreProvider.overrideWithValue(SecureCredentialStore()),
        audioBackendProvider.overrideWithValue(backend),
        audioHandlerProvider.overrideWithValue(handler),
      ],
      child: const EncoreApp(),
    ),
  );
}

/// Declares the app as a music player to the system: media volume stream,
/// "music" content type (Bluetooth / car routing, Do Not Disturb rules) and
/// the focus rules that make a call or a navigation prompt pause or duck the
/// music and let it resume afterwards. `just_audio` applies these attributes
/// to ExoPlayer and handles the interruption events itself.
Future<void> _configureAudioSession() async {
  try {
    final session = await AudioSession.instance;
    await session.configure(const AudioSessionConfiguration.music());
  } on Object catch (error) {
    Log.warn('audio', 'audio session was not configured', error);
  }
}

Future<EncoreAudioHandler> _initAudioService() {
  perfSpan('audioService.init');
  return AudioService.init<EncoreAudioHandler>(
    builder: EncoreAudioHandler.new,
    config: AudioServiceConfig(
      androidNotificationChannelId: 'app.encore.player.playback',
      androidNotificationChannelName: '${AppBranding.name} playback',
      // White bars on transparent (the launcher mipmap is opaque, which the
      // status bar paints as a white square). Kept by res/raw/keep.xml.
      androidNotificationIcon: 'drawable/ic_stat_encore',
      androidNotificationOngoing: false,
      androidStopForegroundOnPause: true,
      notificationColor: kDefaultAccent,
      preloadArtwork: true,
      androidBrowsableRootExtras: const {
        'android.media.browse.SEARCH_SUPPORTED': true,
        'android.media.browse.CONTENT_STYLE_SUPPORTED': true,
        'android.media.browse.CONTENT_STYLE_BROWSABLE_HINT': 2, // grid
        'android.media.browse.CONTENT_STYLE_PLAYABLE_HINT': 1, // list
      },
    ),
  ).whenComplete(() => PerfMonitor.instance.end('audioService.init'));
}

@visibleForTesting
void perfSpan(String name) => PerfMonitor.instance.begin(name);
