/// Typed failures and a minimal `Result` type used at repository boundaries.
///
/// Rationale (ADR-016, docs/02-architecture.md section 11): the inherited code
/// swallowed errors in 100+ empty `catch` blocks. New code returns a [Result]
/// so callers must decide what a failure means, and tests can assert on it.
library;

/// Why an operation failed. Sealed so `switch` is exhaustive.
sealed class AppFailure implements Exception {
  const AppFailure(this.message, {this.cause, this.stackTrace});

  /// Human-readable, **secret-free** description (safe to log and show).
  final String message;

  /// Underlying error, never shown to users.
  final Object? cause;
  final StackTrace? stackTrace;

  /// Whether retrying the same operation later can plausibly succeed.
  bool get isRetryable;

  @override
  String toString() => '$runtimeType: $message';
}

/// No route to the server, DNS failure, timeout, TLS handshake problems.
final class NetworkFailure extends AppFailure {
  const NetworkFailure(super.message, {super.cause, super.stackTrace});

  @override
  bool get isRetryable => true;
}

/// Credentials rejected or session expired.
final class AuthFailure extends AppFailure {
  const AuthFailure(super.message, {super.cause, super.stackTrace});

  @override
  bool get isRetryable => false;
}

/// The server answered but reported an error or an unexpected payload.
final class ServerFailure extends AppFailure {
  const ServerFailure(
    super.message, {
    this.statusCode,
    this.serverCode,
    this.code,
    super.cause,
    super.stackTrace,
  });

  /// HTTP status, when the failure came from an HTTP response.
  final int? statusCode;

  /// The word a service of ours gives its error (the fetch service's
  /// `rate_limited`, `daily_limit`), when it gave one.
  final String? code;

  /// Subsonic error code (e.g. 40 = wrong credentials, 70 = not found).
  final int? serverCode;

  /// An HTTP 5xx can pass. A Subsonic error arrives as HTTP 200 with a code in
  /// the body, so there is no status to look at: only the generic code 0 can
  /// be a passing glitch (an internal hiccup); 10 (missing parameter), 20/30
  /// (version mismatch), 43 (conflicting auth), 50 (not authorised) and 60
  /// (trial over) are the same answer every time. Treating them as retryable
  /// froze the strict-FIFO outbox behind one rejected edit for ever (B1).
  @override
  bool get isRetryable {
    final status = statusCode;
    if (status != null) return status >= 500;
    final code = serverCode;
    if (code != null) return code == 0;
    return true;
  }
}

/// The requested entity does not exist (locally or remotely).
final class NotFoundFailure extends AppFailure {
  const NotFoundFailure(super.message, {super.cause, super.stackTrace});

  @override
  bool get isRetryable => false;
}

/// Disk full, file missing/corrupt, database error.
final class StorageFailure extends AppFailure {
  const StorageFailure(super.message, {super.cause, super.stackTrace});

  @override
  bool get isRetryable => false;
}

/// The operation was cancelled by the caller (not an error to report).
final class CancelledFailure extends AppFailure {
  const CancelledFailure([super.message = 'Cancelled']);

  @override
  bool get isRetryable => false;
}

/// A bug or an unclassified exception. Always logged with its stack trace.
final class UnexpectedFailure extends AppFailure {
  const UnexpectedFailure(super.message, {super.cause, super.stackTrace});

  @override
  bool get isRetryable => false;
}

/// Success value or [AppFailure].
sealed class Result<T> {
  const Result();

  const factory Result.ok(T value) = Ok<T>;
  const factory Result.err(AppFailure failure) = Err<T>;

  bool get isOk => this is Ok<T>;
  bool get isErr => this is Err<T>;

  T? get valueOrNull => switch (this) {
        Ok<T>(:final value) => value,
        Err<T>() => null,
      };

  AppFailure? get failureOrNull => switch (this) {
        Ok<T>() => null,
        Err<T>(:final failure) => failure,
      };

  /// Returns the value or throws the failure (use in tests / at app edges).
  T getOrThrow() => switch (this) {
        Ok<T>(:final value) => value,
        Err<T>(:final failure) => throw failure,
      };

  R when<R>({
    required R Function(T value) ok,
    required R Function(AppFailure failure) err,
  }) =>
      switch (this) {
        Ok<T>(:final value) => ok(value),
        Err<T>(:final failure) => err(failure),
      };

  Result<R> map<R>(R Function(T value) transform) => switch (this) {
        Ok<T>(:final value) => Result<R>.ok(transform(value)),
        Err<T>(:final failure) => Result<R>.err(failure),
      };
}

final class Ok<T> extends Result<T> {
  const Ok(this.value);
  final T value;
}

final class Err<T> extends Result<T> {
  const Err(this.failure);
  final AppFailure failure;
}

/// Runs [body] and converts any thrown error into an [Err].
///
/// [AppFailure]s are passed through; everything else becomes an
/// [UnexpectedFailure] so nothing is silently lost.
Future<Result<T>> guard<T>(Future<T> Function() body) async {
  try {
    return Result<T>.ok(await body());
  } on AppFailure catch (failure) {
    return Result<T>.err(failure);
  } on Object catch (error, stackTrace) {
    return Result<T>.err(
      UnexpectedFailure(
        'Unexpected error: ${error.runtimeType}',
        cause: error,
        stackTrace: stackTrace,
      ),
    );
  }
}
