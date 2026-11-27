import 'package:drift/drift.dart';

import 'fingerprint.dart';

/// The columns of a `tracks` row that the old-formula key is made of (`legacyAudioKey`), for a raw query over [alias], and the key made of them. One place, so the
/// planner, the stale marking and the merge settle all ask the same question of the same columns (N-38).
String legacyKeyColumns([String alias = 't']) =>
    '$alias.size AS size, $alias.suffix AS suffix, $alias.bit_rate AS bit_rate, '
    '$alias.duration_sec AS duration_sec, $alias.sampling_rate AS sampling_rate, '
    '$alias.bit_depth AS bit_depth';

String legacyKeyOfRow(QueryRow row) => legacyAudioKey(
      size: row.read<int?>('size'),
      suffix: row.read<String?>('suffix'),
      bitRate: row.read<int?>('bit_rate'),
      durationSec: row.read<int?>('duration_sec'),
      samplingRate: row.read<int?>('sampling_rate'),
      bitDepth: row.read<int?>('bit_depth'),
    );
