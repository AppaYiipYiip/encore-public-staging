import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// What a page that finds a song inside its list keeps while the person finds (docs/design S-15 and S-17: a playlist's and Liked Songs'
/// "Find in playlist", N-25 and N-32): whether the finding page is open, the words typed (settled after Search's own 90 ms wait) and the last
/// answer, kept on screen until the next one arrives so the list never blinks between two letters. One copy for both pages, so the two can
/// never behave differently; each page only says what its answer is ([T]: the entries' positions of a playlist, the ids of the liked songs) and
/// how to turn it into the places of its own list.
///
/// A page owns one and builds the finding page from it (`_FindingPage`, with a [PlaylistFindBar]); [onChanged] is its `setState`.
class ListFinder<T> {
  ListFinder({required this.onChanged});

  /// The page redraws: something this keeps has changed.
  final VoidCallback onChanged;

  final controller = TextEditingController();
  final focus = FocusNode();

  /// The finding page is open (the field has taken the top of the page).
  bool open = false;

  /// The words typed, settled and trimmed; empty shows the whole list.
  String query = '';

  T? _held;
  Timer? _debounce;

  void dispose() {
    _debounce?.cancel();
    controller.dispose();
    focus.dispose();
  }

  /// Back to the page as it was, with nothing typed. Does not redraw: for a page that is being redrawn anyway (it now shows another playlist).
  void reset() {
    _debounce?.cancel();
    controller.clear();
    open = false;
    query = '';
    _held = null;
  }

  void openFinding() {
    open = true;
    onChanged();
  }

  /// The arrow and Back: the whole list again, as it was, with nothing typed.
  void close() {
    focus.unfocus();
    reset();
    onChanged();
  }

  void typed(String text) {
    // As in Search: the index is fast enough for every letter; the short wait only joins quick typing.
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 90), () {
      query = text.trim();
      onChanged();
    });
  }

  /// Empties the field and shows the whole list; the finding stays open for the next word.
  void clear() {
    _debounce?.cancel();
    controller.clear();
    focus.requestFocus();
    query = '';
    _held = null;
    onChanged();
  }

  /// The answer to show for the words typed now: [found] when it has arrived, else the one before it (so the list stays while the next is
  /// worked out). Ask for it only while [query] is not empty.
  T? hold(AsyncValue<T> found) {
    if (found.hasValue) _held = found.requireValue;
    return _held;
  }
}
