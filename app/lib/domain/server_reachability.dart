/// What the address probes last found out about the person's server (docs/31 CN-5 to CN-14): the one RAW fact about the server itself. It is
/// held by `EndpointResolver` and says nothing about the network, nothing about Android's internet check and nothing about what any screen shows.
enum ServerFinding {
  /// Nobody has looked yet, or the network changed since: what was found says nothing about the new network.
  unknown,

  /// An address proved it is the server (or a request to it just worked).
  answering,

  /// A look at every address found none that answers.
  silent,

  /// A look found none that proves itself, and at least one answered with the key of ANOTHER server (docs/31 CN-11, O-6).
  anotherServer,
}

/// The ONE state of "can I reach my server" (P1-17, AUDIT B-17), the same for every reader: the strip above the player, the grey rows and the
/// words under them, the player's refusal of a song that is not downloaded, the settings pages. Three raw facts make it ([reachabilityOf]):
/// the link ([ServerFinding] is the third, the others are the network kind and Android's own "internet found"); a reader that needs the state
/// reads `serverReachabilityProvider` and nothing underneath it.
///
/// Which server is meant: the Encore server's door (the address that proves itself with a signed answer). Whether the MUSIC server behind it
/// answers is not part of this: it shows only as the failure of a browse call, and the sync reports it apart (`SyncStats.browseFailure`, AUDIT B-77).
enum ServerReachability {
  /// Nobody has looked yet (the first second of the app, or just after a change of network): nothing is greyed, nothing is said, a song may be tried.
  unknown,

  /// The server answers.
  ok,

  /// No network at all (airplane mode, no Wi-Fi and no data). Certain and at once: nothing is looked up, nothing is waited for.
  noNetwork,

  /// A network on which Android found no internet (4G with no data, a Wi-Fi with a sign-in page) and the server does not answer. The person's
  /// own word for it, like [noNetwork], is "offline": "connect" is the way out.
  noInternet,

  /// Internet is found and the server alone does not answer.
  serverAway,

  /// An address answers, but with the key of another server (docs/31 CN-11): nothing is sent to it. Not an outage of the internet.
  wrongServer;

  /// The person's server cannot be reached as far as the app is concerned: what is not on the phone cannot be fetched. [unknown] is not away:
  /// not knowing is no reason to grey a row or to refuse a song.
  bool get isAway => this != unknown && this != ok;

  /// The person has no internet, whether there is no network at all or Android found none on it: "connect" is the way out, as opposed to
  /// [serverAway] and [wrongServer], where the internet is there and the server is the problem.
  bool get isOffline => this == noNetwork || this == noInternet;
}

/// The judgement, immediate (the blink filter of `serverReachabilityProvider` is not part of it): no network is [ServerReachability.noNetwork] whatever was found
/// before; with a network the look at the server decides, and Android's [internetFound] (`null`: it cannot say, internet is assumed) only
/// chooses between [ServerReachability.noInternet] and "the server alone is away" when the server is silent. A server that ANSWERS is ok whatever Android says: a home
/// Wi-Fi with no line out still reaches the home server.
ServerReachability reachabilityOf({
  required bool hasNetwork,
  required ServerFinding finding,
  bool? internetFound,
}) {
  if (!hasNetwork) return ServerReachability.noNetwork;
  return switch (finding) {
    ServerFinding.unknown => ServerReachability.unknown,
    ServerFinding.answering => ServerReachability.ok,
    ServerFinding.anotherServer => ServerReachability.wrongServer,
    ServerFinding.silent => internetFound == false
        ? ServerReachability.noInternet
        : ServerReachability.serverAway,
  };
}
