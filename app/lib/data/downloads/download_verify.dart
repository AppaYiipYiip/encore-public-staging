/// Is a finished download really the audio we asked for? (B23)
///
/// The old check was "at least 1 KiB", which accepts a login page, an error
/// message or a half-finished file as a song. Returns the reason a file must
/// not be kept, or null when it looks right.
String? verifyDownload({
  required String path,
  required int size,
  required List<int> head,
  int? expectedBytes,
  bool original = false,
}) {
  if (size < 1024) return 'Downloaded file is empty';
  // Only an original is served byte for byte, so only there is a size to
  // compare. Bigger than expected is fine (the file may have been re-tagged
  // since the last sync); smaller means it was cut off.
  if (original &&
      expectedBytes != null &&
      expectedBytes > 0 &&
      size < expectedBytes) {
    return 'Downloaded file is incomplete ($size of $expectedBytes bytes)';
  }
  final extension = _extensionOf(path);
  if (!_looksLike(extension, head)) {
    return 'The server did not send audio ($extension expected)';
  }
  return null;
}

String _extensionOf(String path) {
  final name = path.split(RegExp(r'[\\/]')).last;
  final dot = name.lastIndexOf('.');
  return dot < 0 ? '' : name.substring(dot + 1).toLowerCase();
}

bool _startsWith(List<int> head, String text, {int at = 0}) {
  if (head.length < at + text.length) return false;
  for (var i = 0; i < text.length; i++) {
    if (head[at + i] != text.codeUnitAt(i)) return false;
  }
  return true;
}

/// Unknown extensions are accepted: this guards against the common failures
/// (an error page, a login page), it is not a format validator.
bool _looksLike(String extension, List<int> head) {
  switch (extension) {
    case 'flac':
      return _startsWith(head, 'fLaC') || _startsWith(head, 'ID3');
    case 'opus':
    case 'ogg':
    case 'oga':
      return _startsWith(head, 'OggS');
    case 'mp3':
    case 'aac':
      // MP3 and ADTS streams have no real header; some files start with
      // padding. Only turn away what is clearly a text page (HTML, JSON).
      return !(head.isNotEmpty && (head[0] == 0x3C || head[0] == 0x7B));
    case 'm4a':
    case 'mp4':
    case 'alac':
      return _startsWith(head, 'ftyp', at: 4);
    case 'wav':
      return _startsWith(head, 'RIFF');
    default:
      return true;
  }
}
