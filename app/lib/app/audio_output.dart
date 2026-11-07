import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/logger.dart';

/// What kind of output the phone's sound goes to now.
enum AudioOutputKind { speaker, wired, bluetooth, other }

/// Where the phone's sound goes right now, as Android says it (the full player's output row, P1-25, D-66).
@immutable
class AudioOutputInfo {
  const AudioOutputInfo({required this.name, required this.kind});

  /// The phone's own speaker: what there is when nothing else is connected, and what the phone says when it cannot be asked.
  static const AudioOutputInfo thisPhone =
      AudioOutputInfo(name: 'This phone', kind: AudioOutputKind.speaker);

  /// The name shown to the person: "This phone", "Headphones", or the name of a Bluetooth device ("Galaxy Buds2").
  final String name;
  final AudioOutputKind kind;

  /// Reads what the Android side sends (`{name, kind}`); anything unreadable is [thisPhone].
  static AudioOutputInfo fromMap(Object? map) {
    if (map is! Map) return thisPhone;
    final name = (map['name'] as String?)?.trim() ?? '';
    final kind = switch (map['kind']) {
      'bluetooth' => AudioOutputKind.bluetooth,
      'wired' => AudioOutputKind.wired,
      'speaker' => AudioOutputKind.speaker,
      'other' => AudioOutputKind.other,
      _ => AudioOutputKind.speaker,
    };
    if (kind == AudioOutputKind.speaker) return thisPhone;
    return AudioOutputInfo(
        name: name.isEmpty ? _generic(kind) : name, kind: kind);
  }

  static String _generic(AudioOutputKind kind) => switch (kind) {
        AudioOutputKind.bluetooth => 'Bluetooth',
        AudioOutputKind.wired => 'Headphones',
        _ => 'Another output',
      };

  @override
  bool operator ==(Object other) =>
      other is AudioOutputInfo && other.name == name && other.kind == kind;

  @override
  int get hashCode => Object.hash(name, kind);
}

/// The phone's audio output: where the sound goes now (and when that changes) and Android's own chooser. Playback routing is an OS concern; the
/// app shows it and puts the right switcher one tap away. Tests replace it.
abstract interface class AudioOutputService {
  /// The output now, then every change (a headset plugged in, a Bluetooth device gone).
  Stream<AudioOutputInfo> watch();

  /// Android's own output chooser: `true` when one was shown.
  Future<bool> showSwitcher();
}

class ChannelAudioOutput implements AudioOutputService {
  ChannelAudioOutput([MethodChannel? channel])
      : _channel = channel ?? const MethodChannel('app.encore/audio_output');

  final MethodChannel _channel;
  final StreamController<AudioOutputInfo> _changes =
      StreamController<AudioOutputInfo>.broadcast();
  bool _listening = false;

  void _listen() {
    if (_listening) return;
    _listening = true;
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'outputChanged') {
        _changes.add(AudioOutputInfo.fromMap(call.arguments));
      }
    });
  }

  @override
  Stream<AudioOutputInfo> watch() async* {
    _listen();
    yield await _current();
    yield* _changes.stream;
  }

  Future<AudioOutputInfo> _current() async {
    try {
      return AudioOutputInfo.fromMap(
          await _channel.invokeMethod<Object?>('currentOutput'));
    } on MissingPluginException {
      return AudioOutputInfo.thisPhone; // not on a phone (tests, desktop)
    } on PlatformException catch (error) {
      Log.warn('audio', 'current output unavailable', error.message);
      return AudioOutputInfo.thisPhone;
    }
  }

  @override
  Future<bool> showSwitcher() async {
    try {
      return await _channel.invokeMethod<bool>('showOutputSwitcher') ?? false;
    } on PlatformException catch (error) {
      Log.warn('audio', 'output switcher unavailable', error.message);
      return false;
    } on MissingPluginException {
      return false;
    }
  }
}

final audioOutputServiceProvider =
    Provider<AudioOutputService>((ref) => ChannelAudioOutput());

/// Where the sound goes now, live. Until Android has answered it is the phone's own speaker, so the player's bottom row never jumps.
final audioOutputProvider = StreamProvider.autoDispose<AudioOutputInfo>(
    (ref) => ref.watch(audioOutputServiceProvider).watch());
