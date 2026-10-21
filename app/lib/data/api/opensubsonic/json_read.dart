/// Tolerant JSON readers for Subsonic/OpenSubsonic payloads.
///
/// Servers disagree about types (ints as strings, single objects instead of
/// one-element lists because the JSON is derived from XML, `starred` as an ISO
/// date). Everything funnels through these helpers so DTO parsing never throws
/// on a merely *odd* payload.
library;

int? readInt(Object? v) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v) ?? double.tryParse(v)?.toInt();
  return null;
}

double? readDouble(Object? v) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v);
  return null;
}

String? readString(Object? v) {
  if (v == null) return null;
  final s = v.toString();
  return s.isEmpty ? null : s;
}

bool readBool(Object? v, {bool fallback = false}) {
  if (v is bool) return v;
  if (v is String) return v.toLowerCase() == 'true';
  if (v is num) return v != 0;
  return fallback;
}

/// Parses an ISO-8601 date to UTC epoch milliseconds, or `null`.
int? readDateMs(Object? v) {
  if (v is! String || v.isEmpty) return null;
  // Navidrome emits nanosecond precision ("...:34.835687354Z"); Dart handles
  // microseconds, so trim the fraction defensively.
  final trimmed = v.replaceFirstMapped(
    RegExp(r'(\.\d{6})\d+'),
    (m) => m.group(1)!,
  );
  return DateTime.tryParse(trimmed)?.toUtc().millisecondsSinceEpoch;
}

Map<String, dynamic>? readMap(Object? v) =>
    v is Map ? v.cast<String, dynamic>() : null;

/// A list of objects, tolerating `null`, a single object, or a list.
List<Map<String, dynamic>> readObjectList(Object? v) {
  if (v == null) return const [];
  if (v is Map) return [v.cast<String, dynamic>()];
  if (v is List) {
    return [
      for (final item in v)
        if (item is Map) item.cast<String, dynamic>(),
    ];
  }
  return const [];
}

List<String> readStringList(Object? v) {
  if (v == null) return const [];
  if (v is List) {
    return [
      for (final item in v)
        if (item != null && item.toString().isNotEmpty) item.toString(),
    ];
  }
  final single = readString(v);
  return single == null ? const [] : [single];
}
