/// The rules and state of Encore's Devices and Sessions (docs/29).
///
/// Pure Dart with a single dependency (`meta`), so the same code runs in the
/// Android app, in the server hub and in the browser listener, and cannot
/// import Flutter even by accident.
library;

export 'src/clock.dart';
export 'src/drift.dart';
export 'src/protocol.dart';
export 'src/reducer.dart';
