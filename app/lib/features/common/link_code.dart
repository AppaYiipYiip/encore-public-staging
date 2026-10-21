import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../design/tokens.dart';

/// A QR code of [data] (an invitation link), drawn dark on white the way a code
/// is read, whatever the app's theme. The new person's own camera reads it and
/// offers to open the link in Encore.
///
/// Drawn with a painter at a fixed size, not with `QrImageView`: that one lays
/// itself out with a `LayoutBuilder`, which a dialog cannot measure.
class LinkCode extends StatelessWidget {
  const LinkCode({super.key, required this.data, this.size = 168});

  /// What the code holds.
  final String data;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(Space.sm),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(Radii.card),
        ),
        child: SizedBox.square(
          dimension: size,
          child: CustomPaint(
            painter: QrPainter(
              data: data,
              version: QrVersions.auto,
              errorCorrectionLevel: QrErrorCorrectLevel.M,
              eyeStyle: const QrEyeStyle(
                eyeShape: QrEyeShape.square,
                color: Colors.black,
              ),
              dataModuleStyle: const QrDataModuleStyle(
                dataModuleShape: QrDataModuleShape.square,
                color: Colors.black,
              ),
            ),
          ),
        ),
      );
}
