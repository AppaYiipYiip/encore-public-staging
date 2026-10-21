import 'package:flutter/painting.dart';

/// In-memory decoded-image cache sizing (the disk cache for covers lives in
/// `coverCacheManager`). A shelf of 150 px covers decodes small, so 1000
/// entries / 150 MB keeps scrolling back and forth free of re-decoding
/// without letting the cache grow without bound.
abstract final class ImageCacheConfig {
  static void configure() {
    PaintingBinding.instance.imageCache
      ..maximumSize = 1000
      ..maximumSizeBytes = 150 << 20;
  }
}
