/// Canonical form of a server base URL: `scheme://host[:port][/path]` with no
/// trailing slash, query or fragment.
///
/// `Uri.replace(query: '', fragment: '')` yields `http://host:4533?#`; code
/// that builds request URLs by string concatenation then put the whole REST
/// path into the fragment, so the server received `GET /` and answered with
/// its web page. That made every stream request fail ("Source error") and the
/// player silently skip to the next track (docs/11-feedback-log.md FB-004).
Uri canonicalBaseUrl(Uri uri) {
  final path = uri.path.replaceAll(RegExp(r'/+$'), '');
  return Uri(
    scheme: uri.scheme,
    userInfo: uri.userInfo.isEmpty ? null : uri.userInfo,
    host: uri.host,
    port: uri.hasPort ? uri.port : null,
    path: path,
  );
}
