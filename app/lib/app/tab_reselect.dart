import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// The main tabs, by position in the tab bar (the order of the branches in `router.dart`).
abstract final class MainTab {
  static const home = 0;
  static const search = 1;
  static const library = 2;
}

/// A second tap on the tab that is already open (N-22, owner, 13 Nov 2026: "after a search, tapping Search again should show the first search
/// page as if nothing had been searched. The same for Home and the other main tabs"). The router already goes back to the tab's root page; what
/// a page that stays mounted there still holds (a typed query, a chosen chip, how far it is scrolled) is for the page itself to put back, so the
/// shell only says WHICH tab was tapped again and each tab's page answers with [TabReselectListening.onTabReselected]. [serial] makes two
/// taps in a row two events.
class TabReselected {
  const TabReselected(this.tab, this.serial);

  final int tab;
  final int serial;
}

class TabReselectNotifier extends Notifier<TabReselected?> {
  @override
  TabReselected? build() => null;

  void reselected(int tab) =>
      state = TabReselected(tab, (state?.serial ?? 0) + 1);
}

final tabReselectProvider =
    NotifierProvider<TabReselectNotifier, TabReselected?>(
        TabReselectNotifier.new);

extension TabReselectListening on WidgetRef {
  /// Runs [reset] when [tab] is tapped again while it is open. Call it from `build`.
  void onTabReselected(int tab, VoidCallback reset) {
    listen<TabReselected?>(tabReselectProvider, (_, event) {
      if (event != null && event.tab == tab) reset();
    });
  }
}

/// Scrolls the page whose [context] this is back to its top (the page's own primary scroll view).
void scrollPageToTop(BuildContext context) {
  final controller = PrimaryScrollController.maybeOf(context);
  if (controller == null || !controller.hasClients) return;
  controller.animateTo(0,
      duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
}
