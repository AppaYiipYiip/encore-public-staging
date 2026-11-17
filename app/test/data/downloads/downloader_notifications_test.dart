import 'package:background_downloader/background_downloader.dart';
import 'package:encore/data/downloads/background_downloader_transport.dart';
import 'package:flutter_test/flutter_test.dart';

/// docs/33 PB-38 and docs/design S-95 (P2-29): the downloader posts NO card of its own. The one card of the downloads is the app's (a card for the whole
/// download, server stage included); a second one from the downloader would be two cards for one download, and its words ("Some of your music is
/// ready offline") were the ones that could say something untrue.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('the downloader has no notification configured for the downloads group',
      () async {
    final transport = BackgroundDownloaderTransport();
    addTearDown(transport.dispose);

    final task = DownloadTask(
      url: 'http://home.test/song.opus',
      group: transport.group,
    );

    expect(FileDownloader().notificationConfigForTask(task), isNull,
        reason: 'a configured group card is a second card');
  });
}
