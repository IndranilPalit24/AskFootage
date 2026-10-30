import type { Recording } from '../../api/generated/types';
import { parseTimeOfDay, SECONDS_PER_DAY } from '../../lib/time';

// Static, so created once: 00:00 to 24:00 every 6 hours.
const ticks = (
  <div className="timeline__ticks" aria-hidden="true">
    {['00:00', '06:00', '12:00', '18:00', '24:00'].map((tick, index) => (
      <span key={tick} style={{ left: `${index * 25}%` }}>
        {tick}
      </span>
    ))}
  </div>
);

function percent(seconds: number): string {
  const clamped = Math.min(Math.max(seconds, 0), SECONDS_PER_DAY);
  return `${((clamped / SECONDS_PER_DAY) * 100).toFixed(3)}%`;
}

interface DayTimelineProps {
  recordings: Recording[];
  /** Matched moment, in seconds since midnight. */
  matchStart: number;
  matchEnd: number;
  /** e.g. "Matched at 10:42 on Thu 29 Oct" */
  label: string;
}

/** 00:00-24:00 bar: the day's recordings as light segments, the matched moment in the accent colour. */
export function DayTimeline({ recordings, matchStart, matchEnd, label }: DayTimelineProps) {
  return (
    <section className="card timeline" aria-labelledby="timeline-heading">
      <h2 id="timeline-heading">Day timeline</h2>
      <div className="timeline__bar" role="img" aria-label={label}>
        {/* One pass: recordings not measured yet (length 0) have no segment. */}
        {recordings.flatMap((recording) =>
          recording.lengthSeconds > 0
            ? [
                <span
                  key={recording.id}
                  className="timeline__segment"
                  style={{ left: percent(parseTimeOfDay(recording.startTime)), width: percent(recording.lengthSeconds) }}
                />,
              ]
            : [],
        )}
        <span
          className="timeline__match"
          data-testid="timeline-match"
          style={{ left: percent(matchStart), width: percent(Math.max(0, matchEnd - matchStart)) }}
        />
      </div>
      {ticks}
    </section>
  );
}
