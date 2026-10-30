import type { DaySummary } from '../../api/generated/types';
import { dayOfMonth, formatWeekdayShort } from '../../lib/dates';

interface DayStripProps {
  /** The 7 days, oldest first; the last one is today. */
  days: DaySummary[];
  selected: string;
  onSelect: (day: string) => void;
}

/** One toggle button per day: weekday over date ("Thu" over "29"); the selected one is pressed. */
export function DayStrip({ days, selected, onSelect }: DayStripProps) {
  return (
    <div className="day-strip" role="group" aria-label="Day">
      {days.map((entry) => (
        <button
          key={entry.day}
          type="button"
          className="day-btn"
          aria-pressed={entry.day === selected}
          onClick={() => onSelect(entry.day)}
        >
          <span className="day-btn__weekday">{formatWeekdayShort(entry.day)}</span>{' '}
          <span className="day-btn__date">{dayOfMonth(entry.day)}</span>
        </button>
      ))}
    </div>
  );
}
