import 'package:flutter/material.dart';

import '../../design/tokens.dart';

/// "Find in playlist" at rest (docs/design S-17, N-25): the field between the playlist's header lines and its buttons, Spotify's own place
/// and words. It looks like a field and is a button: tapping it opens [PlaylistFindBar] at the top of the page, so the keyboard never
/// covers what the person is looking at.
class PlaylistFindField extends StatelessWidget {
  const PlaylistFindField({super.key, required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final shape = BorderRadius.circular(Radii.card);
    return Semantics(
      button: true,
      label: 'Find in playlist',
      excludeSemantics: true,
      child: Material(
        color: c.onBg.withValues(alpha: 0.10),
        borderRadius: shape,
        child: InkWell(
          onTap: onTap,
          borderRadius: shape,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Padding(
              padding: const EdgeInsets.symmetric(
                  horizontal: Space.md, vertical: Space.xs),
              child: Row(
                children: [
                  Icon(Icons.search_rounded, color: c.onBgMuted),
                  const SizedBox(width: Space.sm),
                  Flexible(
                    child: Text(
                      'Find in playlist',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: context.text.bodyLarge?.copyWith(
                          color: c.onBgMuted, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The field once it is open: the arrow, the field and a clear button, built like Search's own field (S-12), so nothing new is learned.
/// The arrow closes the finding and shows the whole playlist as it was; the clear button empties the field and keeps it open.
class PlaylistFindBar extends StatelessWidget {
  const PlaylistFindBar({
    super.key,
    required this.controller,
    required this.focusNode,
    required this.onChanged,
    required this.onClear,
    required this.onClose,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final ValueChanged<String> onChanged;
  final VoidCallback onClear;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(
          Space.xs, Space.xs, Space.gutter, 0),
      child: Row(
        children: [
          IconButton(
            tooltip: 'Back',
            icon: const Icon(Icons.arrow_back_rounded),
            onPressed: onClose,
          ),
          Expanded(
            // The clear button appears with the first letter, not 90 ms later when the list has followed.
            child: ValueListenableBuilder<TextEditingValue>(
              valueListenable: controller,
              builder: (context, value, _) => TextField(
                controller: controller,
                focusNode: focusNode,
                autofocus: true,
                onChanged: onChanged,
                onSubmitted: (_) => focusNode.unfocus(),
                textInputAction: TextInputAction.search,
                style: context.text.bodyLarge,
                decoration: InputDecoration(
                  hintText: 'Find in playlist',
                  prefixIcon: const Icon(Icons.search_rounded),
                  suffixIcon: value.text.isEmpty
                      ? null
                      : IconButton(
                          tooltip: 'Clear',
                          icon: const Icon(Icons.close_rounded),
                          onPressed: onClear,
                        ),
                  filled: true,
                  fillColor: c.surfaceHigh,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(Radii.card),
                    borderSide: BorderSide.none,
                  ),
                  contentPadding: const EdgeInsets.symmetric(vertical: 14),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
