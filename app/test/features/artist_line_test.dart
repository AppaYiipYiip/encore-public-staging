import 'package:encore/features/common/artist_line.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show RenderParagraph;
import 'package:flutter_test/flutter_test.dart';

/// Owner, 7 Nov 2026: "its only one artist clickable i think". Every artist of a song is a tap of its own.
void main() {
  Widget app(List<String> names, void Function(String) onTap,
          {double width = 600}) =>
      MaterialApp(
        home: Scaffold(
          body: Center(
              child: SizedBox(
                  width: width, child: ArtistLine(names: names, onTap: onTap))),
        ),
      );

  List<InlineSpan> spans(WidgetTester tester) {
    final rich = tester.widget<RichText>(find.byType(RichText).first);
    // Text.rich wraps what it is given in a span of its own
    final outer = rich.text as TextSpan;
    return (outer.children!.single as TextSpan).children!;
  }

  testWidgets('shows the names in order, with commas between them',
      (tester) async {
    await tester.pumpWidget(
        app(['Drake', 'Kanye West', 'Lil Wayne', 'Eminem'], (_) {}));

    expect(
        find.textContaining('Drake, Kanye West, Lil Wayne, Eminem',
            findRichText: true),
        findsOneWidget);
  });

  testWidgets('a tap on a name is a tap on that name only', (tester) async {
    final tapped = <String>[];
    await tester.pumpWidget(
        app(['Drake', 'Kanye West', 'Lil Wayne', 'Eminem'], tapped.add));

    // the first name starts at the left edge of the line
    final left = tester.getTopLeft(find.byType(RichText).first);
    await tester.tapAt(left + const Offset(4, 8));
    // the others, through the paragraph's own geometry
    final render =
        tester.renderObject<RenderParagraph>(find.byType(RichText).first);
    for (final name in ['Kanye West', 'Lil Wayne', 'Eminem']) {
      final text = 'Drake, Kanye West, Lil Wayne, Eminem';
      final start = text.indexOf(name);
      final boxes = render.getBoxesForSelection(
          TextSelection(baseOffset: start, extentOffset: start + name.length));
      final point = render.localToGlobal(boxes.first.toRect().center);
      await tester.tapAt(point);
    }

    expect(tapped, ['Drake', 'Kanye West', 'Lil Wayne', 'Eminem']);
  });

  testWidgets('a tap on the comma between two names opens nobody',
      (tester) async {
    final tapped = <String>[];
    await tester.pumpWidget(app(['Drake', 'Eminem'], tapped.add));
    final render =
        tester.renderObject<RenderParagraph>(find.byType(RichText).first);
    final boxes = render.getBoxesForSelection(
        const TextSelection(baseOffset: 5, extentOffset: 6)); // the comma
    await tester.tapAt(render.localToGlobal(boxes.first.toRect().center));

    expect(tapped, isEmpty);
  });

  testWidgets('a long list wraps onto a second line, so no name is cut off',
      (tester) async {
    await tester.pumpWidget(app(
        ['Corey Taylor', 'Dave Grohl', 'Rick Nielsen', 'Scott Reeder'], (_) {},
        width: 220));

    final size = tester.getSize(find.byType(RichText).first);
    expect(size.height, greaterThan(24 * 1.2), reason: 'two lines');
    final taps =
        spans(tester).whereType<TextSpan>().where((s) => s.recognizer != null);
    expect(taps.length, 4);
  });

  testWidgets('when the names change the taps follow them', (tester) async {
    final tapped = <String>[];
    await tester.pumpWidget(app(['A', 'B'], tapped.add));
    await tester.pumpWidget(app(['A', 'B', 'C'], tapped.add));

    final last = spans(tester)
        .whereType<TextSpan>()
        .lastWhere((s) => s.recognizer != null);
    (last.recognizer as TapGestureRecognizer).onTap!();

    expect(tapped, ['C']);
  });
}
