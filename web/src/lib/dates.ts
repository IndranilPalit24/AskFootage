// Calendar-day helpers. A day is a YYYY-MM-DD string from the API. All maths is done in UTC so the
// browser's time zone and clock never shift a day; "today" always comes from the server (GET /api/days).

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

const DAY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

interface DayParts {
  year: number;
  /** 0-11 */
  month: number;
  date: number;
  /** 0 = Sunday */
  weekday: number;
}

/** True when the text is a real calendar date written YYYY-MM-DD. */
export function isIsoDay(text: string): boolean {
  const match = DAY_PATTERN.exec(text);
  if (!match) return false;
  const [year, month, date] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const value = new Date(Date.UTC(year, month - 1, date));
  return value.getUTCFullYear() === year && value.getUTCMonth() === month - 1 && value.getUTCDate() === date;
}

function parts(day: string): DayParts {
  const match = DAY_PATTERN.exec(day);
  if (!match) throw new Error(`Not a day: ${day}`);
  const value = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return {
    year: value.getUTCFullYear(),
    month: value.getUTCMonth(),
    date: value.getUTCDate(),
    weekday: value.getUTCDay(),
  };
}

function pad2(value: number): string {
  return String(value).padStart(2, '0');
}

/** The day n days after (or before, when n is negative) the given day. */
export function addDays(day: string, n: number): string {
  const { year, month, date } = parts(day);
  const value = new Date(Date.UTC(year, month, date + n));
  return `${value.getUTCFullYear()}-${pad2(value.getUTCMonth() + 1)}-${pad2(value.getUTCDate())}`;
}

/** "Thursday 29 October" */
export function formatDayNoYear(day: string): string {
  const { month, date, weekday } = parts(day);
  return `${WEEKDAYS[weekday]} ${date} ${MONTHS[month]}`;
}

/** "Thu 29 Oct" */
export function formatShortDay(day: string): string {
  const { month, date, weekday } = parts(day);
  return `${WEEKDAYS[weekday].slice(0, 3)} ${date} ${MONTHS[month].slice(0, 3)}`;
}

/** "Thu" */
export function formatWeekdayShort(day: string): string {
  return WEEKDAYS[parts(day).weekday].slice(0, 3);
}

/** 29 */
export function dayOfMonth(day: string): number {
  return parts(day).date;
}
