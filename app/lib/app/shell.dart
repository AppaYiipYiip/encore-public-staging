import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../features/common/connection_banner.dart';
import '../features/home/you_drawer.dart';
import '../features/player/mini_player.dart';

/// Bottom navigation + persistent mini-player around the tab branches
/// (docs/06-ux-spec.md section 3).
class AppShell extends StatelessWidget {
  const AppShell({super.key, required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  static const _destinations = [
    NavigationDestination(
      icon: Icon(Icons.home_outlined),
      selectedIcon: Icon(Icons.home_rounded),
      label: 'Home',
    ),
    NavigationDestination(
      icon: Icon(Icons.search_rounded),
      selectedIcon: Icon(Icons.search_rounded),
      label: 'Search',
    ),
    NavigationDestination(
      icon: Icon(Icons.library_music_outlined),
      selectedIcon: Icon(Icons.library_music_rounded),
      label: 'Your Library',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // The drawer the Home avatar opens (S-27, D-34); it opens only from there, never from an edge swipe on a tab.
      drawer: const YouDrawer(),
      drawerEnableOpenDragGesture: false,
      body: navigationShell,
      bottomNavigationBar: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const ConnectionBanner(),
          const MiniPlayer(),
          NavigationBar(
            selectedIndex: navigationShell.currentIndex,
            destinations: _destinations,
            labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
            onDestinationSelected: (index) => navigationShell.goBranch(
              index,
              // Re-tapping the current tab returns to its root (Spotify-like).
              initialLocation: index == navigationShell.currentIndex,
            ),
          ),
        ],
      ),
    );
  }
}
