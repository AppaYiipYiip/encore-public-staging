/// How long ago a piece of news was, in the few words the bell has room for (docs/design S-24): "10 min", "Today", "Yesterday", "Monday".
String newsTimeLabel(DateTime now, DateTime at) {
  final ago = now.difference(at);
  if (ago < const Duration(minutes: 1)) return 'Now';
  if (ago < const Duration(hours: 1)) return '${ago.inMinutes} min';

  final today = DateTime(now.year, now.month, now.day);
  final day = DateTime(at.year, at.month, at.day);
  final days = today.difference(day).inDays;
  if (days <= 0) return 'Today';
  if (days == 1) return 'Yesterday';
  if (days < 7) return _weekdays[at.weekday - 1];
  final date = '${at.day} ${_months[at.month - 1]}';
  return at.year == now.year ? date : '$date ${at.year}';
}

const _weekdays = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
];

const _months = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];
