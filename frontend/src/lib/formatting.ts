import type { OverviewRange } from '$lib/overview';

const OVERVIEW_TIME_ZONE = 'America/Sao_Paulo';

export function formatOverviewTimeLabel(value: string, range: OverviewRange) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  const timeOptions: Intl.DateTimeFormatOptions = {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: OVERVIEW_TIME_ZONE
  };

  const dateOptions: Intl.DateTimeFormatOptions = {
    month: '2-digit',
    day: '2-digit',
    timeZone: OVERVIEW_TIME_ZONE
  };

  if (range === '1h' || range === '24h') {
    return new Intl.DateTimeFormat('en-US', timeOptions).format(date);
  }

  return new Intl.DateTimeFormat('en-US', dateOptions).format(date);
}
