import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Phones stay upright, like the music apps people know: the full player and the lists were drawn for portrait, and turned on its side the
/// mini player ran under the system buttons and the cover filled the whole screen (QA round 1, R1-4 and R1-5). A screen whose shorter side
/// is 600 dp or more (a tablet, the PC) turns freely. Layouts for a phone on its side are a later job (RC2).
class OrientationPolicy extends StatefulWidget {
  const OrientationPolicy({super.key, required this.child});

  final Widget child;

  @override
  State<OrientationPolicy> createState() => _OrientationPolicyState();
}

class _OrientationPolicyState extends State<OrientationPolicy> {
  bool? _phone;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final phone = MediaQuery.sizeOf(context).shortestSide < 600;
    if (phone == _phone) return;
    _phone = phone;
    unawaited(SystemChrome.setPreferredOrientations(phone
        ? const [DeviceOrientation.portraitUp, DeviceOrientation.portraitDown]
        : DeviceOrientation.values));
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
