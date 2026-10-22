import 'package:flutter/material.dart';

/// The one way a bottom sheet is shown (P1-12, E11-E13).
///
/// A sheet left to the platform defaults reaches the bottom edge of the screen, and with the three navigation buttons (or the
/// gesture bar, or the keyboard) the last row sat under them: tappable, but not reachable. This sheet keeps its content clear of the
/// system bars at the bottom, lifts it above the keyboard, never grows past nine tenths of the screen, and shows the drag handle.
Future<T?> showEncoreSheet<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  bool showDragHandle = true,

  /// Above the mini-player and the tab bar (a sheet opened from inside a tab otherwise sits below them).
  bool useRootNavigator = false,
}) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: showDragHandle,
    useRootNavigator: useRootNavigator,
    builder: (sheet) => _SheetFrame(child: builder(sheet)),
  );
}

/// Keeps what is inside clear of the bottom system bar and the keyboard.
class _SheetFrame extends StatelessWidget {
  const _SheetFrame({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SafeArea(top: false, child: child),
    );
  }
}
