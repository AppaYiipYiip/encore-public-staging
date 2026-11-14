import 'playability.dart' show AwayCause;

/// The words of Search while the server is away (drawn 5 Nov 2026, docs/design S-11, S-12, S-13; P1-16). They say what cannot be DONE, never
/// what cannot be reached, so they stay true before and after the catalogue moves to the server (D-51); and they follow the strip's two
/// causes ([AwayCause]), so the page and the strip agree on one screen.

/// The field's hint while the server is away: what can still be searched (the phone's own copy of the library).
const String kSearchHintAway = 'Search your music';

/// The one quiet last line under the results the phone found by itself.
String moreResultsNeed(AwayCause cause) => switch (cause) {
      AwayCause.noInternet => 'More results need a connection.',
      AwayCause.serverSilent => 'More results need your server.',
    };

/// The heading of a search that found nothing in the phone's own library while the rest cannot be asked.
String nothingInYourMusic(String query) =>
    'Nothing in your music matches ‘$query’.';

/// Under [nothingInYourMusic]: what could not be searched, in the words of its cause.
String onlyYourMusicSearched(AwayCause cause) => switch (cause) {
      AwayCause.noInternet => 'Connect to search more.',
      AwayCause.serverSilent =>
        "Your server isn't answering, so only your music can be searched.",
    };

/// The genre page while the server is away: its title, then what cannot be done, and the way back.
const String kGenreUnavailableTitle = 'Not available right now';
const String kGenreBack = 'Back to Search';

String browsingNeeds(AwayCause cause) => switch (cause) {
      AwayCause.noInternet => 'Browsing needs a connection.',
      AwayCause.serverSilent => 'Browsing needs your server.',
    };
