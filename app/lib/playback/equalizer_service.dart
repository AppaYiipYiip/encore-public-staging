import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:just_audio/just_audio.dart' as ja;
import 'package:shared_preferences/shared_preferences.dart';

import '../core/logger.dart';
import '../domain/eq_presets.dart';
import 'audio_units.dart';

@immutable
class EqualizerState {
  const EqualizerState({
    this.available = false,
    this.enabled = false,
    this.centresHz = const [],
    this.gains = const [],
    this.minDb = -15,
    this.maxDb = 15,
    this.presetId,
  });

  /// The platform exposes an equaliser (Android, after first playback load).
  final bool available;
  final bool enabled;
  final List<double> centresHz;
  final List<double> gains;
  final double minDb;
  final double maxDb;

  /// Preset the current gains came from; `null` when edited by hand.
  final String? presetId;

  EqualizerState copyWith({
    bool? enabled,
    List<double>? gains,
    String? presetId,
    bool clearPreset = false,
  }) =>
      EqualizerState(
        available: available,
        enabled: enabled ?? this.enabled,
        centresHz: centresHz,
        gains: gains ?? this.gains,
        minDb: minDb,
        maxDb: maxDb,
        presetId: clearPreset ? null : (presetId ?? this.presetId),
      );
}

/// Drives the Android equaliser and remembers the setting.
///
/// The band layout is device specific (usually 5 bands, -15..+15 dB), so
/// gains are stored per band *index count* and presets are interpolated onto
/// whatever the device offers.
class EqualizerService {
  EqualizerService(this._equalizer);

  final ja.AndroidEqualizer? _equalizer;

  static const _kEnabled = 'encore.eq.enabled';
  static const _kGains = 'encore.eq.gains';
  static const _kPreset = 'encore.eq.preset';

  final StreamController<EqualizerState> _changes =
      StreamController<EqualizerState>.broadcast();
  EqualizerState _state = const EqualizerState();
  ja.AndroidEqualizerParameters? _parameters;
  SharedPreferences? _prefs;

  EqualizerState get state => _state;
  Stream<EqualizerState> get changes => _changes.stream;

  /// Waits for the platform equaliser and restores the saved curve.
  Future<void> init() async {
    final eq = _equalizer;
    if (eq == null) return;
    try {
      final params = await eq.parameters.timeout(const Duration(seconds: 15));
      _parameters = params;
      _prefs = await SharedPreferences.getInstance();
      final minDb = fromPlatformGain(params.minDecibels);
      final maxDb = fromPlatformGain(params.maxDecibels);
      final centres = [for (final b in params.bands) b.centerFrequency];
      var gains = List<double>.filled(params.bands.length, 0);
      final saved = _prefs?.getStringList(_kGains);
      final presetId = _prefs?.getString(_kPreset);
      if (saved != null && saved.length == gains.length) {
        gains = [for (final g in saved) double.tryParse(g) ?? 0];
      } else if (EqPreset.byId(presetId) != null) {
        gains =
            EqPreset.byId(presetId)!.forBands(centres, min: minDb, max: maxDb);
      }
      final enabled = _prefs?.getBool(_kEnabled) ?? false;
      _state = EqualizerState(
        available: true,
        enabled: enabled,
        centresHz: centres,
        gains: gains,
        minDb: minDb,
        maxDb: maxDb,
        presetId: presetId,
      );
      await _apply();
      _changes.add(_state);
    } on Object catch (error) {
      Log.debug('audio', 'equaliser not available: $error');
    }
  }

  Future<void> setEnabled(bool value) async {
    _state = _state.copyWith(enabled: value);
    await _apply();
    _publish();
  }

  Future<void> setBandGain(int index, double db) async {
    if (index < 0 || index >= _state.gains.length) return;
    final gains = [..._state.gains];
    gains[index] = db.clamp(_state.minDb, _state.maxDb);
    _state = _state.copyWith(gains: gains, clearPreset: true);
    await _apply();
    _publish();
  }

  Future<void> applyPreset(EqPreset preset) async {
    final gains =
        preset.forBands(_state.centresHz, min: _state.minDb, max: _state.maxDb);
    _state = _state.copyWith(
      gains: gains,
      presetId: preset.id,
      enabled: preset.id == EqPreset.flat.id ? _state.enabled : true,
    );
    await _apply();
    _publish();
  }

  Future<void> reset() => applyPreset(EqPreset.flat);

  Future<void> _apply() async {
    final eq = _equalizer;
    final params = _parameters;
    if (eq == null || params == null) return;
    try {
      await eq.setEnabled(_state.enabled);
      for (var i = 0; i < params.bands.length; i++) {
        await params.bands[i].setGain(
            toPlatformGain(i < _state.gains.length ? _state.gains[i] : 0));
      }
    } on Object catch (error) {
      Log.warn('audio', 'equaliser update failed', error);
    }
  }

  void _publish() {
    _changes.add(_state);
    final prefs = _prefs;
    if (prefs == null) return;
    unawaited(prefs.setBool(_kEnabled, _state.enabled));
    unawaited(prefs.setStringList(
        _kGains, [for (final g in _state.gains) g.toStringAsFixed(2)]));
    final preset = _state.presetId;
    if (preset == null) {
      unawaited(prefs.remove(_kPreset));
    } else {
      unawaited(prefs.setString(_kPreset, preset));
    }
  }

  Future<void> dispose() => _changes.close();
}
