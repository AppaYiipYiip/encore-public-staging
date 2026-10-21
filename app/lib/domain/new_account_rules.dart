/// What a person who joins a server by invitation may choose (docs/39 F3).
///
/// The server has the same rules and the final say (`encore_people/invites.py`);
/// the sentences are the server's own, so a person hears one voice whether the
/// phone or the server speaks. Checking here saves a round trip and keeps the
/// invitation unused.
library;

final RegExp _username = RegExp(r'^[a-z][a-z0-9._-]{2,31}$');

/// Names that would confuse the people on the server or look like something
/// they are not.
const Set<String> _reserved = {
  'admin',
  'administrator',
  'root',
  'owner',
  'everyone',
  'shared',
  'system',
  'navidrome',
  'encore',
  'guest',
  'support',
  'server',
};

/// `null` when [name] is acceptable, else a plain sentence.
String? checkNewUsername(String name) {
  if (!_username.hasMatch(name)) {
    return 'Choose a name of 3 to 32 characters in lower case: letters, '
        'digits, dots, dashes or underscores, starting with a letter.';
  }
  if (_reserved.contains(name)) {
    return 'That name is not available. Choose another.';
  }
  return null;
}

/// What a person typed, made into a name the server takes where that is
/// unambiguous: the first letter is a capital on most keyboards.
String suggestUsername(String typed) => typed.trim().toLowerCase();

/// `null` when [password] is acceptable, else a plain sentence.
String? checkNewPassword(String password) {
  if (password.length < 8 || password.length > 200) {
    return 'Choose a password of at least 8 characters.';
  }
  return null;
}
