import 'package:dio/dio.dart';
import 'package:meta/meta.dart';

import '../../core/network_policy.dart';
import '../../core/result.dart';
import '../../domain/invite_link.dart';

/// What the people service says about an invitation before it is used.
@immutable
class InvitationInfo {
  const InvitationInfo({
    required this.inviter,
    required this.serverName,
    required this.address,
  });

  /// Who sent the invitation.
  final String inviter;

  /// What the server is called.
  final String serverName;

  /// Where to sign in once the account exists (the server's public address).
  final Uri? address;
}

/// The account that was made.
@immutable
class JoinedAccount {
  const JoinedAccount({required this.username, required this.address});

  final String username;

  /// Where to sign in; `null` when the service did not say (the address the
  /// invitation came from is then the one).
  final Uri? address;
}

/// The friend's side of an invitation, over the people service's public
/// routes (docs/39 F3): the app makes the account itself, so nobody is sent
/// to a browser and back.
///
/// The two calls are the ones the invitation page makes; the rules about names
/// and passwords are the service's, and its words are shown as they are.
class PeopleJoinClient {
  PeopleJoinClient({Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: const Duration(seconds: 8),
              receiveTimeout: const Duration(seconds: 20),
              validateStatus: (_) => true,
            ));

  final Dio _dio;

  /// Every answer is read here, whatever its status: a refusal carries the
  /// sentence to show.
  static final _any = Options(validateStatus: (_) => true);

  /// Who invited, and what the server is called. Never throws.
  Future<Result<InvitationInfo>> info(InviteLink link) => guard(() async {
        final response = await _call(
            link, () => _dio.getUri<Object?>(link.infoUrl, options: _any));
        final data = _map(response);
        if (link.encore) {
          // Who invited comes with the invitation; what the server is called is asked separately and is a nicety.
          var name = '';
          try {
            final named = await _dio.getUri<Object?>(link.nameUrl,
                options:
                    _any.copyWith(receiveTimeout: const Duration(seconds: 6)));
            final body = named.data;
            if (body is Map && body['name'] is String) {
              name = body['name'] as String;
            }
          } on DioException {
            // The name is optional.
          }
          return InvitationInfo(
            inviter: '${data['invitedBy'] ?? ''}',
            serverName: name,
            address: null,
          );
        }
        return InvitationInfo(
          inviter: '${data['inviter'] ?? ''}',
          serverName: '${data['server'] ?? ''}',
          address: _address(data['address']),
        );
      });

  /// Makes the account. The password goes in the body of the request, never in
  /// an address, and never over plain http to an address on the internet.
  /// Never throws.
  Future<Result<JoinedAccount>> redeem(
    InviteLink link, {
    required String username,
    required String password,
  }) =>
      guard(() async {
        final unsafe = cleartextProblem(link.redeemUrl);
        if (unsafe != null) {
          throw UnexpectedFailure('Your password was not sent. $unsafe');
        }
        final response = await _call(
          link,
          () => _dio.postUri<Object?>(
            link.redeemUrl,
            data: link.encore
                ? {
                    'code': link.code,
                    'username': username,
                    'password': password,
                    'deviceName': 'Phone',
                  }
                : {'username': username, 'password': password},
            options: _any,
          ),
        );
        final data = _map(response);
        if (link.encore) {
          return JoinedAccount(username: username, address: null);
        }
        return JoinedAccount(
          username: '${data['username'] ?? username}',
          address: _address(data['address']),
        );
      });

  Future<Response<Object?>> _call(
    InviteLink link,
    Future<Response<Object?>> Function() send,
  ) async {
    final Response<Object?> response;
    try {
      response = await send();
    } on DioException catch (error) {
      throw NetworkFailure(
        "Can't reach ${link.server.host}. Check your internet connection "
        'and try again.',
        cause: error,
      );
    }
    final status = response.statusCode ?? 0;
    if (status >= 200 && status < 300) return response;
    final said = _words(response);
    throw switch (status) {
      404 => NotFoundFailure(said ?? _gone),
      429 => ServerFailure(
          said ?? 'Too many tries. Wait a minute and try again.',
          statusCode: status,
          code: 'wait',
        ),
      _ when status >= 500 => ServerFailure(
          'The server is having trouble. Try again in a minute.',
          statusCode: status,
        ),
      _ => ServerFailure(said ?? 'That did not work. Try again.',
          statusCode: status),
    };
  }

  static const _gone =
      'This invitation is not valid any more. Ask whoever sent it for a new '
      'one.';

  static String? _words(Response<Object?> response) {
    final data = response.data;
    if (data is Map && data['error'] is String) return data['error'] as String;
    // An Encore server's one error shape: {"error": {"code", "message"}}.
    if (data is Map && data['error'] is Map) {
      final message = (data['error'] as Map)['message'];
      if (message is String && message.isNotEmpty) return message;
    }
    return null;
  }

  static Map<Object?, Object?> _map(Response<Object?> response) {
    final data = response.data;
    if (data is Map) return data;
    throw const ServerFailure('The server answered something unexpected.');
  }

  static Uri? _address(Object? value) {
    if (value is! String || value.trim().isEmpty) return null;
    final uri = Uri.tryParse(value.trim());
    return uri == null || uri.host.isEmpty ? null : uri;
  }
}
