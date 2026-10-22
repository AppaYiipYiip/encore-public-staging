import 'dart:async';

import 'package:flutter/material.dart' show ThemeMode;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meta/meta.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../data/alerts/alerts_service.dart' show AlertSettings;
import '../../domain/audio_quality.dart';
import '../../domain/household.dart';
import '../../playback/replay_gain.dart';

/// User preferences (set-and-forget behaviour, docs/06-ux-spec.md 4.9).
@immutable
class AppSettings {
  const AppSettings({
    this.themeMode = ThemeMode.dark,
    this.amoledBlack = false,
    this.lyricsTextScale = 1.0,
    this.keepScreenOnInLyrics = true,
    this.wifiOnlyDownloads = true,
    this.requestPortalUrl,
    this.requestPortalUser,
    this.requestsEnabled = true,
    this.fetchServiceUrl,
    this.instantPlayEnabled = true,
    this.streamQualityWifi = AudioQuality.original,
    this.streamQualityMobile = AudioQuality.high,
    this.downloadQuality = AudioQuality.high,
    this.downloadLimitBytes,
    this.backgroundSyncHours = 6,
    this.playbackSpeed = 1.0,
    this.replayGainMode = ReplayGainMode.track,
    this.replayGainBoost = false,
    this.libraryScope = LibraryScope.automatic,
    this.showNewOnServer = true,
    this.privateListening = false,
    this.alertsOnServer = true,
    this.alertsReleases = true,
    this.alertsImports = true,
    this.perfOverlay = false,
  });

  final ThemeMode themeMode;
  final bool amoledBlack;

  /// 0.8 .. 1.6 multiplier of the lyrics font size.
  final double lyricsTextScale;
  final bool keepScreenOnInLyrics;
  final bool wifiOnlyDownloads;

  /// Base URL of the request portal (e.g. `http://192.168.1.10:8700`).
  final String? requestPortalUrl;

  /// Login for the request portal (password lives in secure storage).
  final String? requestPortalUser;

  /// Request / Import buttons are shown. Switched off by "I don't have a
  /// download service" so a server without one is never nagged (ADR-052).
  final bool requestsEnabled;

  /// Address of the instant-play companion service once found (ADR-057).
  final String? fetchServiceUrl;

  /// A song that is not in the library plays by being fetched on request.
  final bool instantPlayEnabled;

  /// Quality when streaming on Wi-Fi / Ethernet (ADR-036).
  final AudioQuality streamQualityWifi;

  /// Quality when streaming on a metered mobile connection.
  final AudioQuality streamQualityMobile;

  /// Default quality for new downloads.
  final AudioQuality downloadQuality;

  /// Cap on the space offline music may use; `null` = no cap.
  final int? downloadLimitBytes;

  /// How often the app syncs while closed; 0 = never.
  final int backgroundSyncHours;

  /// 0.5 .. 2.0; pitch is preserved.
  final double playbackSpeed;

  final ReplayGainMode replayGainMode;

  /// -6 .. +6 dB on top of the ReplayGain value.
  /// Quiet places: levelling may also make a quiet song louder (up to +9 dB through the loudness enhancer, which can distort).
  /// Off by default: levelling only ever turns loud songs down, so the phone's volume buttons stay the one volume (P1-13).
  final bool replayGainBoost;

  /// What Your Library lists on a server shared with other people.
  final LibraryScope libraryScope;

  /// Home shelf with what *everyone* added to the server recently.
  final bool showNewOnServer;

  /// No now-playing ping, no scrobble, no local history.
  final bool privateListening;

  /// Notify when an album by an artist you play reaches your server.
  final bool alertsOnServer;

  /// Notify about new releases (not on the server yet) by those artists.
  final bool alertsReleases;

  /// Notify when songs of an imported playlist arrive.
  final bool alertsImports;

  /// A counter over the whole app: frames per second, memory, CPU
  /// (Settings > About > Diagnostics). For finding slow spots.
  final bool perfOverlay;

  AlertSettings get alerts => AlertSettings(
        onServer: alertsOnServer,
        releases: alertsReleases,
        imports: alertsImports,
      );

  AppSettings copyWith({
    ThemeMode? themeMode,
    bool? amoledBlack,
    double? lyricsTextScale,
    bool? keepScreenOnInLyrics,
    bool? wifiOnlyDownloads,
    String? requestPortalUrl,
    bool clearRequestPortalUrl = false,
    String? requestPortalUser,
    bool clearRequestPortalUser = false,
    bool? requestsEnabled,
    String? fetchServiceUrl,
    bool clearFetchServiceUrl = false,
    bool? instantPlayEnabled,
    AudioQuality? streamQualityWifi,
    AudioQuality? streamQualityMobile,
    AudioQuality? downloadQuality,
    int? downloadLimitBytes,
    bool clearDownloadLimit = false,
    int? backgroundSyncHours,
    double? playbackSpeed,
    ReplayGainMode? replayGainMode,
    bool? replayGainBoost,
    LibraryScope? libraryScope,
    bool? showNewOnServer,
    bool? privateListening,
    bool? alertsOnServer,
    bool? alertsReleases,
    bool? alertsImports,
    bool? perfOverlay,
  }) =>
      AppSettings(
        themeMode: themeMode ?? this.themeMode,
        amoledBlack: amoledBlack ?? this.amoledBlack,
        lyricsTextScale: lyricsTextScale ?? this.lyricsTextScale,
        keepScreenOnInLyrics: keepScreenOnInLyrics ?? this.keepScreenOnInLyrics,
        wifiOnlyDownloads: wifiOnlyDownloads ?? this.wifiOnlyDownloads,
        requestPortalUrl: clearRequestPortalUrl
            ? null
            : (requestPortalUrl ?? this.requestPortalUrl),
        requestPortalUser: clearRequestPortalUser
            ? null
            : (requestPortalUser ?? this.requestPortalUser),
        requestsEnabled: requestsEnabled ?? this.requestsEnabled,
        fetchServiceUrl: clearFetchServiceUrl
            ? null
            : (fetchServiceUrl ?? this.fetchServiceUrl),
        instantPlayEnabled: instantPlayEnabled ?? this.instantPlayEnabled,
        streamQualityWifi: streamQualityWifi ?? this.streamQualityWifi,
        streamQualityMobile: streamQualityMobile ?? this.streamQualityMobile,
        downloadQuality: downloadQuality ?? this.downloadQuality,
        downloadLimitBytes: clearDownloadLimit
            ? null
            : (downloadLimitBytes ?? this.downloadLimitBytes),
        backgroundSyncHours: backgroundSyncHours ?? this.backgroundSyncHours,
        playbackSpeed: playbackSpeed ?? this.playbackSpeed,
        replayGainMode: replayGainMode ?? this.replayGainMode,
        replayGainBoost: replayGainBoost ?? this.replayGainBoost,
        libraryScope: libraryScope ?? this.libraryScope,
        showNewOnServer: showNewOnServer ?? this.showNewOnServer,
        privateListening: privateListening ?? this.privateListening,
        alertsOnServer: alertsOnServer ?? this.alertsOnServer,
        alertsReleases: alertsReleases ?? this.alertsReleases,
        alertsImports: alertsImports ?? this.alertsImports,
        perfOverlay: perfOverlay ?? this.perfOverlay,
      );
}

class SettingsController extends Notifier<AppSettings> {
  static const _kTheme = 'encore.theme';
  static const _kAmoled = 'encore.amoled';
  static const _kLyricsScale = 'encore.lyricsScale';
  static const _kKeepOn = 'encore.lyricsKeepOn';
  static const _kWifiOnly = 'encore.wifiOnlyDownloads';
  static const _kPortal = 'encore.requestPortal';
  static const _kPortalUser = 'encore.requestPortalUser';
  static const _kRequestsEnabled = 'encore.requestsEnabled';
  static const _kFetchService = 'encore.fetchService';
  static const _kInstantPlay = 'encore.instantPlay';
  static const _kQualityWifi = 'encore.quality.wifi';
  static const _kQualityMobile = 'encore.quality.mobile';
  static const _kQualityDownload = 'encore.quality.download';
  static const _kDownloadLimit = 'encore.downloadLimitBytes';
  static const _kBackgroundSync = 'encore.backgroundSyncHours';
  static const _kSpeed = 'encore.playbackSpeed';
  static const _kReplayGain = 'encore.replayGain';
  static const _kBoost = 'encore.replayGainBoost';
  static const _kScope = 'encore.libraryScope';
  static const _kShowNew = 'encore.showNewOnServer';
  static const _kPrivate = 'encore.privateListening';
  static const kAlertsOnServer = 'encore.alerts.server';
  static const kAlertsReleases = 'encore.alerts.releases';
  static const kAlertsImports = 'encore.alerts.imports';
  static const _kPerfOverlay = 'encore.perfOverlay';

  SharedPreferences? _prefs;

  @override
  AppSettings build() {
    // Read before the first frame by `bootstrap()`: no theme flash, and
    // "private listening" is already on for music that starts right away (B17).
    final preloaded = ref.read(initialSettingsProvider);
    if (preloaded != null) return preloaded;
    // Tests and the background job: defaults now, the saved values a moment later.
    unawaited(_load());
    return const AppSettings();
  }

  /// Every saved preference as settings (a missing or damaged value falls back
  /// to its default or is kept in range). Pure: used at start-up before the
  /// first frame, and by the async fallback below.
  static AppSettings fromPrefs(SharedPreferences p) {
    return AppSettings(
      themeMode: ThemeMode.values.firstWhere(
        (m) => m.name == p.getString(_kTheme),
        orElse: () => ThemeMode.dark,
      ),
      amoledBlack: p.getBool(_kAmoled) ?? false,
      lyricsTextScale: (p.getDouble(_kLyricsScale) ?? 1.0).clamp(0.8, 1.6),
      keepScreenOnInLyrics: p.getBool(_kKeepOn) ?? true,
      wifiOnlyDownloads: p.getBool(_kWifiOnly) ?? true,
      requestPortalUrl: p.getString(_kPortal),
      requestPortalUser: p.getString(_kPortalUser),
      requestsEnabled: p.getBool(_kRequestsEnabled) ?? true,
      fetchServiceUrl: p.getString(_kFetchService),
      instantPlayEnabled: p.getBool(_kInstantPlay) ?? true,
      streamQualityWifi: AudioQuality.byId(p.getString(_kQualityWifi),
          fallback: AudioQuality.original),
      streamQualityMobile: AudioQuality.byId(p.getString(_kQualityMobile),
          fallback: AudioQuality.high),
      downloadQuality: AudioQuality.byId(p.getString(_kQualityDownload),
          fallback: AudioQuality.high),
      downloadLimitBytes: p.getInt(_kDownloadLimit),
      backgroundSyncHours: (p.getInt(_kBackgroundSync) ?? 6).clamp(0, 168),
      playbackSpeed: (p.getDouble(_kSpeed) ?? 1.0).clamp(0.5, 2.0),
      replayGainMode: ReplayGainMode.values.firstWhere(
        (m) => m.name == p.getString(_kReplayGain),
        orElse: () => ReplayGainMode.track,
      ),
      replayGainBoost: p.getBool(_kBoost) ?? false,
      libraryScope: LibraryScope.byName(p.getString(_kScope)),
      showNewOnServer: p.getBool(_kShowNew) ?? true,
      privateListening: p.getBool(_kPrivate) ?? false,
      alertsOnServer: p.getBool(kAlertsOnServer) ?? true,
      alertsReleases: p.getBool(kAlertsReleases) ?? true,
      alertsImports: p.getBool(kAlertsImports) ?? true,
      perfOverlay: p.getBool(_kPerfOverlay) ?? false,
    );
  }

  Future<void> _load() async {
    try {
      final p = _prefs = await SharedPreferences.getInstance();
      state = fromPrefs(p);
    } on Object {
      // Preferences are a convenience; defaults are always usable.
    }
  }

  Future<void> _save(Future<void> Function(SharedPreferences p) write) async {
    try {
      final p = _prefs ??= await SharedPreferences.getInstance();
      await write(p);
    } on Object {
      // Ignore: the in-memory value still applies for this session.
    }
  }

  void setThemeMode(ThemeMode mode) {
    state = state.copyWith(themeMode: mode);
    _save((p) => p.setString(_kTheme, mode.name));
  }

  void setAmoled(bool value) {
    state = state.copyWith(amoledBlack: value);
    _save((p) => p.setBool(_kAmoled, value));
  }

  void setLyricsTextScale(double value) {
    final v = value.clamp(0.8, 1.6);
    state = state.copyWith(lyricsTextScale: v);
    _save((p) => p.setDouble(_kLyricsScale, v));
  }

  void setKeepScreenOnInLyrics(bool value) {
    state = state.copyWith(keepScreenOnInLyrics: value);
    _save((p) => p.setBool(_kKeepOn, value));
  }

  void setWifiOnlyDownloads(bool value) {
    state = state.copyWith(wifiOnlyDownloads: value);
    _save((p) => p.setBool(_kWifiOnly, value));
  }

  void setRequestPortalUrl(String? url) {
    final clean = url?.trim();
    if (clean == null || clean.isEmpty) {
      state = state.copyWith(clearRequestPortalUrl: true);
      _save((p) => p.remove(_kPortal));
    } else {
      state = state.copyWith(requestPortalUrl: clean);
      _save((p) => p.setString(_kPortal, clean));
    }
  }

  void setStreamQualityWifi(AudioQuality q) {
    state = state.copyWith(streamQualityWifi: q);
    _save((p) => p.setString(_kQualityWifi, q.id));
  }

  void setStreamQualityMobile(AudioQuality q) {
    state = state.copyWith(streamQualityMobile: q);
    _save((p) => p.setString(_kQualityMobile, q.id));
  }

  void setDownloadQuality(AudioQuality q) {
    state = state.copyWith(downloadQuality: q);
    _save((p) => p.setString(_kQualityDownload, q.id));
  }

  /// `null` removes the cap.
  void setDownloadLimitBytes(int? bytes) {
    if (bytes == null || bytes <= 0) {
      state = state.copyWith(clearDownloadLimit: true);
      _save((p) => p.remove(_kDownloadLimit));
    } else {
      state = state.copyWith(downloadLimitBytes: bytes);
      _save((p) => p.setInt(_kDownloadLimit, bytes));
    }
  }

  void setPlaybackSpeed(double speed) {
    final v = speed.clamp(0.5, 2.0);
    state = state.copyWith(playbackSpeed: v);
    _save((p) => p.setDouble(_kSpeed, v));
  }

  /// 0 turns background sync off.
  void setBackgroundSyncHours(int hours) {
    final v = hours.clamp(0, 168);
    state = state.copyWith(backgroundSyncHours: v);
    _save((p) => p.setInt(_kBackgroundSync, v));
  }

  void setReplayGainMode(ReplayGainMode mode) {
    state = state.copyWith(replayGainMode: mode);
    _save((p) => p.setString(_kReplayGain, mode.name));
  }

  void setReplayGainBoost(bool on) {
    state = state.copyWith(replayGainBoost: on);
    _save((p) => p.setBool(_kBoost, on));
  }

  void setLibraryScope(LibraryScope scope) {
    state = state.copyWith(libraryScope: scope);
    _save((p) => p.setString(_kScope, scope.name));
  }

  void setShowNewOnServer(bool value) {
    state = state.copyWith(showNewOnServer: value);
    _save((p) => p.setBool(_kShowNew, value));
  }

  void setPrivateListening(bool value) {
    state = state.copyWith(privateListening: value);
    _save((p) => p.setBool(_kPrivate, value));
  }

  void setAlertsOnServer(bool value) {
    state = state.copyWith(alertsOnServer: value);
    _save((p) => p.setBool(kAlertsOnServer, value));
  }

  void setAlertsReleases(bool value) {
    state = state.copyWith(alertsReleases: value);
    _save((p) => p.setBool(kAlertsReleases, value));
  }

  void setPerfOverlay(bool value) {
    state = state.copyWith(perfOverlay: value);
    _save((p) => p.setBool(_kPerfOverlay, value));
  }

  void setAlertsImports(bool value) {
    state = state.copyWith(alertsImports: value);
    _save((p) => p.setBool(kAlertsImports, value));
  }

  void setRequestPortalUser(String? user) {
    final clean = user?.trim();
    if (clean == null || clean.isEmpty) return;
    state = state.copyWith(requestPortalUser: clean);
    _save((p) => p.setString(_kPortalUser, clean));
  }

  void setFetchServiceUrl(String? url) {
    final clean = url?.trim();
    if (clean == null || clean.isEmpty) {
      state = state.copyWith(clearFetchServiceUrl: true);
      _save((p) => p.remove(_kFetchService));
    } else {
      state = state.copyWith(fetchServiceUrl: clean);
      _save((p) => p.setString(_kFetchService, clean));
    }
  }

  void setInstantPlayEnabled(bool value) {
    state = state.copyWith(instantPlayEnabled: value);
    _save((p) => p.setBool(_kInstantPlay, value));
  }

  /// What belongs to the account that just signed out: the request portal,
  /// the instant-play address and the switches that depend on them, and the
  /// private-listening switch (a new account must not inherit it).
  void forgetServer() {
    state = state.copyWith(
      clearRequestPortalUrl: true,
      clearRequestPortalUser: true,
      clearFetchServiceUrl: true,
      requestsEnabled: true,
      instantPlayEnabled: true,
      privateListening: false,
    );
    _save((p) async {
      for (final key in [
        _kPortal,
        _kPortalUser,
        _kFetchService,
        _kRequestsEnabled,
        _kInstantPlay,
        _kPrivate,
      ]) {
        await p.remove(key);
      }
    });
  }

  void setRequestsEnabled(bool value) {
    state = state.copyWith(requestsEnabled: value);
    _save((p) => p.setBool(_kRequestsEnabled, value));
  }
}

/// The settings read before the first frame (`bootstrap()` overrides it);
/// `null` means "load them asynchronously".
final initialSettingsProvider = Provider<AppSettings?>((ref) => null);

final settingsProvider =
    NotifierProvider<SettingsController, AppSettings>(SettingsController.new);

/// The alert switches read straight from preferences, for the background job
/// (it has no provider container).
Future<AlertSettings> readAlertSettings() async {
  try {
    final p = await SharedPreferences.getInstance();
    return AlertSettings(
      onServer: p.getBool(SettingsController.kAlertsOnServer) ?? true,
      releases: p.getBool(SettingsController.kAlertsReleases) ?? true,
      imports: p.getBool(SettingsController.kAlertsImports) ?? true,
    );
  } on Object {
    return const AlertSettings();
  }
}
