/// Unit conversions for `just_audio`'s Android effects.
///
/// Its Dart API calls the values "decibels" but the native side multiplies by
/// 1000 to get *millibels* (1 dB = 100 mB), so an API value of 1.0 is really
/// 10 dB. Feeding real dB straight in would make a +4 dB loudness boost a
/// +40 dB one. Everything in this app speaks real dB; these two functions are
/// the only place the factor appears (regression: found by reading the
/// plugin source after the first on-device equaliser run showed +/-1.5).
const double kJustAudioGainUnitDb = 10;

/// Real dB -> the value `just_audio` expects.
double toPlatformGain(double db) => db / kJustAudioGainUnitDb;

/// The value `just_audio` reports -> real dB.
double fromPlatformGain(double platformValue) =>
    platformValue * kJustAudioGainUnitDb;
