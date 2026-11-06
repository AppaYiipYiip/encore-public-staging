import 'package:encore/data/downloads/background_downloader_transport.dart';
import 'package:flutter_test/flutter_test.dart';

/// docs/33 PB-38: the phone's notification covers only the phone's stage. When its queue of files empties the server may still hold most of a playlist
/// (the queue is fed a few files at a time and the stages overlap), so the notification must not say that downloads are finished.
void main() {
  test('the notification for an emptied queue never says finished', () {
    final words = '${kDownloadsQueueEmptiedNotification.title} '
            '${kDownloadsQueueEmptiedNotification.body}'
        .toLowerCase();

    expect(words, isNot(contains('finished')));
    expect(words, isNot(contains('complete')));
    expect(words, isNot(contains('all your')));
  });

  test('and it sends the person to the place that does tell how it is going',
      () {
    expect(kDownloadsQueueEmptiedNotification.body, contains('Open Encore'));
  });
}
