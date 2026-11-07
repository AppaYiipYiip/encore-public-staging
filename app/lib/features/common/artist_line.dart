import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

/// The artists of a song on one line, each name a tap of its own (owner, 7 Nov 2026: on "Forever" by four artists only one of them could be
/// pressed). The names wrap onto a second line rather than being cut with "...", because a name that is cut cannot be pressed.
class ArtistLine extends StatefulWidget {
  const ArtistLine({
    super.key,
    required this.names,
    required this.onTap,
    this.style,
    this.maxLines = 2,
  });

  final List<String> names;
  final void Function(String name) onTap;
  final TextStyle? style;
  final int maxLines;

  @override
  State<ArtistLine> createState() => _ArtistLineState();
}

class _ArtistLineState extends State<ArtistLine> {
  List<TapGestureRecognizer> _taps = const [];

  @override
  void initState() {
    super.initState();
    _make();
  }

  @override
  void didUpdateWidget(ArtistLine old) {
    super.didUpdateWidget(old);
    if (old.names.length != widget.names.length) {
      _free();
      _make();
    }
  }

  void _make() {
    _taps = [
      for (var i = 0; i < widget.names.length; i++)
        TapGestureRecognizer()..onTap = () => widget.onTap(widget.names[i]),
    ];
  }

  void _free() {
    for (final tap in _taps) {
      tap.dispose();
    }
  }

  @override
  void dispose() {
    _free();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final names = widget.names;
    return Text.rich(
      TextSpan(children: [
        for (var i = 0; i < names.length; i++) ...[
          TextSpan(text: names[i], recognizer: _taps[i]),
          if (i < names.length - 1) const TextSpan(text: ', '),
        ],
      ]),
      maxLines: widget.maxLines,
      overflow: TextOverflow.ellipsis,
      style: widget.style,
    );
  }
}
