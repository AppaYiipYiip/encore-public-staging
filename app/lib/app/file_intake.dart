import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/logger.dart';

/// A file of songs the person chose: its name and its text.
class PickedFile {
  const PickedFile({required this.name, required this.text});

  final String name;
  final String text;
}

/// Why a file could not be brought in, in words for the person.
class FilePickProblem implements Exception {
  const FilePickProblem(this.message);

  final String message;

  @override
  String toString() => message;
}

/// Lets the person choose a file of songs (a list exported from Spotify or
/// Google). Android's own file chooser, no storage permission: the system
/// hands over only the file that was chosen.
abstract interface class SongFilePicker {
  /// The chosen file, or the files inside it when it is a .zip (Spotify's
  /// "Download your data"); `null` when the person backed out. Throws
  /// [FilePickProblem] with a sentence when the file could not be read.
  Future<List<PickedFile>?> pick();
}

class ChannelSongFilePicker implements SongFilePicker {
  ChannelSongFilePicker([MethodChannel? channel])
      : _channel = channel ?? const MethodChannel('app.encore/files');

  final MethodChannel _channel;

  @override
  Future<List<PickedFile>?> pick() async {
    try {
      final raw = await _channel.invokeMethod<List<Object?>>('pickSongFile');
      if (raw == null) return null;
      return [
        for (final f in raw)
          if (f is Map)
            PickedFile(name: '${f['name'] ?? ''}', text: '${f['text'] ?? ''}'),
      ];
    } on PlatformException catch (error) {
      throw FilePickProblem(error.message ?? 'The file could not be read.');
    } on MissingPluginException {
      Log.debug('files', 'no file chooser on this platform');
      throw const FilePickProblem(
          'Choosing a file is not possible on this device.');
    }
  }
}

final songFilePickerProvider =
    Provider<SongFilePicker>((ref) => ChannelSongFilePicker());
