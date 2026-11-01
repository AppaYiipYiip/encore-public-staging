import 'package:encore/app/orientation_policy.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// QA round 1, R1-4 and R1-5: a phone turned on its side showed a mini player under the system buttons and a cover as wide as the screen.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Future<List<String>> orientationsFor(WidgetTester tester, Size size) async {
    List<String>? chosen;
    tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'SystemChrome.setPreferredOrientations') {
        chosen = (call.arguments as List).cast<String>();
      }
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    await tester.pumpWidget(MediaQuery(
      data: MediaQueryData(size: size),
      child: const OrientationPolicy(child: SizedBox.shrink()),
    ));
    return chosen ?? const [];
  }

  testWidgets('a phone stays upright', (tester) async {
    final chosen = await orientationsFor(tester, const Size(390, 844));

    expect(chosen,
        ['DeviceOrientation.portraitUp', 'DeviceOrientation.portraitDown']);
  });

  testWidgets('a phone already on its side is just as much a phone',
      (tester) async {
    final chosen = await orientationsFor(tester, const Size(844, 390));

    expect(chosen,
        ['DeviceOrientation.portraitUp', 'DeviceOrientation.portraitDown']);
  });

  testWidgets('a tablet or a window on the PC turns freely', (tester) async {
    final chosen = await orientationsFor(tester, const Size(1280, 800));

    expect(chosen, hasLength(4));
  });
}
