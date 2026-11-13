import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

/// The artists of a song on ONE line, each name a tap of its own (owner, 7 Nov 2026: on "Forever" by four artists only one of them could be
/// pressed). The line has the height of a single line whatever the number of artists and scrolls sideways when the names are longer than the
/// room: wrapping onto a second line moved everything below it down, differently from one song to the next ("make it scrollable instead"), and a
/// name cut with "..." cannot be pressed.
class ArtistLine extends StatefulWidget {
  const ArtistLine({
    super.key,
    required this.names,
    required this.onTap,
    this.style,
  });

  final List<String> names;
  final void Function(String name) onTap;
  final TextStyle? style;

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
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Text.rich(
        TextSpan(children: [
          for (var i = 0; i < names.length; i++) ...[
            TextSpan(text: names[i], recognizer: _taps[i]),
            if (i < names.length - 1) const TextSpan(text: ', '),
          ],
        ]),
        maxLines: 1,
        softWrap: false,
        style: widget.style,
      ),
    );
  }
}
