import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/branding.dart';
import '../../app/share_out.dart';
import '../../design/tokens.dart';
import 'diagnostics_screen.dart';
import 'settings_page.dart';

final _ipv4 = RegExp(
    r'\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?::\d{2,5})?\b');
final _tailnetName = RegExp(r'\b(?:[\w-]+\.)+ts\.net\b', caseSensitive: false);
final _urlHost =
    RegExp(r'\b((?:https?|wss?)://)[^\s/"\x27)\]]+', caseSensitive: false);

/// Takes the server's address out of a technical report: the report goes to a person who does not need to know where the server is
/// (the log can hold one, e.g. in a failed request).
String hideAddresses(String text) => text
    .replaceAllMapped(_urlHost, (m) => '${m[1]}<address>')
    .replaceAll(_tailnetName, '<address>')
    .replaceAll(_ipv4, '<address>');

/// What the share sheet carries: the person's own words, then (if they leave it on) the technical report.
/// Pure so the wording is unit-tested.
String buildFeedbackMessage({required String message, String? details}) {
  final b = StringBuffer()
    ..writeln('${AppBranding.name} ${AppBranding.version} - feedback')
    ..writeln()
    ..writeln(message.trim());
  if (details != null && details.trim().isNotEmpty) {
    b
      ..writeln()
      ..writeln('---- technical details (no passwords) ----')
      ..write(hideAddresses(details));
  }
  return b.toString();
}

/// "Report a problem or idea": the way a friend who uses Encore every day tells the person who looks after it what went wrong or what
/// they did not like (docs/tasks/P3-12). It opens the phone's own share sheet (Messages, WhatsApp, e-mail...), so nothing is sent
/// anywhere the person did not choose, and Encore needs no account or address for it.
class ReportProblemScreen extends ConsumerStatefulWidget {
  const ReportProblemScreen({super.key});

  @override
  ConsumerState<ReportProblemScreen> createState() =>
      _ReportProblemScreenState();
}

class _ReportProblemScreenState extends ConsumerState<ReportProblemScreen> {
  final _message = TextEditingController();
  bool _includeDetails = true;
  bool _empty = false;

  @override
  void dispose() {
    _message.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (_message.text.trim().isEmpty) {
      setState(() => _empty = true);
      return;
    }
    final messenger = ScaffoldMessenger.of(context);
    final share = ref.read(shareOutProvider);
    // Read again now so the recent activity is up to date.
    final details =
        _includeDetails ? ref.refresh(diagnosticsReportProvider) : null;
    final text = buildFeedbackMessage(message: _message.text, details: details);
    final opened = await share.text(text);
    if (opened || !mounted) return;
    // No share sheet on this phone: the message can still be pasted anywhere.
    await Clipboard.setData(ClipboardData(text: text));
    messenger.showSnackBar(const SnackBar(
      content: Text('Could not open sharing. The message is copied: '
          'paste it into any chat or e-mail.'),
    ));
  }

  @override
  Widget build(BuildContext context) {
    // Keeps the facts the report needs (server, sync, playback) loaded while the person writes.
    if (_includeDetails) ref.watch(diagnosticsReportProvider);

    return SettingsPage(
      title: 'Report a problem or idea',
      description: 'Tell us what went wrong, or what you did not like. '
          'Your phone\'s share sheet opens next: you choose where it goes.',
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
          child: TextField(
            key: const Key('report-message'),
            controller: _message,
            minLines: 5,
            maxLines: 12,
            keyboardType: TextInputType.multiline,
            textCapitalization: TextCapitalization.sentences,
            onChanged: (_) {
              if (_empty) setState(() => _empty = false);
            },
            decoration: InputDecoration(
              labelText: 'What happened, or what did you not like?',
              alignLabelWithHint: true,
              border: const OutlineInputBorder(),
              errorText: _empty ? 'Write a few words first.' : null,
            ),
          ),
        ),
        SwitchListTile(
          key: const Key('report-include-details'),
          title: const Text('Include technical details'),
          subtitle: const Text('Your phone, the app version, your server\'s '
              'name, the song that was playing and the last few lines of '
              'what the app did. No passwords.'),
          value: _includeDetails,
          onChanged: (v) => setState(() => _includeDetails = v),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: Space.gutter, vertical: Space.sm),
          child: FilledButton.icon(
            key: const Key('report-send'),
            onPressed: _send,
            icon: const Icon(Icons.ios_share_rounded, size: 18),
            label: const Text('Send'),
          ),
        ),
      ],
    );
  }
}
