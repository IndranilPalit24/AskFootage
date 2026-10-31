import type { ReactNode } from 'react';
import type { SearchState } from '../../app/SearchContext';
import { formatShortDay } from '../../lib/dates';
import { ClipCard } from './ClipCard';

interface SearchResultsProps {
  state: SearchState;
  /** The day picked now; when the results are for another day, the count line says which. */
  selectedDay: string | null;
  onRetry: () => void;
  /** Camera id -> name, for each card's time line. */
  cameraNames: ReadonlyMap<string, string>;
}

function countLine(count: number, day: string, selectedDay: string | null): string {
  const clips = count === 1 ? '1 clip' : `${count} clips`;
  return day === selectedDay ? clips : `${clips} on ${formatShortDay(day)}`;
}

/**
 * Status line (in a polite live region) and the result cards. Before the first search the live region is
 * there but empty (so later lines are announced), and it takes no space.
 */
export function SearchResults({ state, selectedDay, onRetry, cameraNames }: SearchResultsProps) {
  let status: ReactNode = null;
  switch (state.phase) {
    case 'idle':
      break;
    case 'loading':
      status = <p className="muted">Searching {formatShortDay(state.day)}&apos;s footage…</p>;
      break;
    case 'error':
      status = (
        <>
          <p className="error-text">{state.error}</p>
          <p className="results-status__action">
            <button type="button" className="btn btn--sm" onClick={onRetry}>
              Try again
            </button>
          </p>
        </>
      );
      break;
    case 'done': {
      const { clips, note } = state.response;
      status = (
        <>
          {clips.length === 0 ? (
            <p>No clips matched on {formatShortDay(state.day)}. Try other words or another day.</p>
          ) : (
            <p className="muted">{countLine(clips.length, state.day, selectedDay)}</p>
          )}
          {note ? <p className="muted">{note}</p> : null}
        </>
      );
      break;
    }
  }

  const clips = state.phase === 'done' ? state.response.clips : [];
  const proofs = state.phase === 'done' ? state.response.proofs : [];
  return (
    <>
      <div className="results-status" aria-live="polite">
        {status}
      </div>
      {clips.length > 0 ? (
        <ul className="clip-list" aria-label="Results">
          {clips.map((clip) => (
            <ClipCard
              key={clip.id}
              clip={clip}
              cameraName={cameraNames.get(clip.camera) ?? clip.camera}
              proof={proofs.find((p) => p.clipId === clip.id)}
            />
          ))}
        </ul>
      ) : null}
    </>
  );
}
