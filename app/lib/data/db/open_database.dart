import 'package:drift_flutter/drift_flutter.dart';

import 'app_database.dart';

/// Opens the production database on a background isolate so queries and bulk
/// sync writes never block the UI thread (R-07).
///
/// File: `<app documents>/encore.sqlite` (managed by `drift_flutter`).
AppDatabase openAppDatabase() => AppDatabase(driftDatabase(name: 'encore'));
