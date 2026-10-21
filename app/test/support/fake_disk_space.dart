import 'package:encore/data/downloads/disk_space.dart';

/// Free space a test can change at will.
class FakeDiskSpace implements DiskSpace {
  FakeDiskSpace([this.free]);

  int? free;

  @override
  Future<int?> freeBytes() async => free;
}
