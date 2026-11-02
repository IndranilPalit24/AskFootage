import type { ReactNode } from 'react';
import type { SearchState } from '../../app/SearchContext';
import { formatShortDay } from '../../lib/dates';
import { EmptyState } from '../../components/EmptyState';
import { ClipListSkeleton } from '../../components/Skeletons';
import { ClipCard } from './ClipCard';
import { FeaturedClipCard } from './FeaturedClipCard';
import { NeedsIndexingPanel } from './NeedsIndexingPanel';

interface SearchResultsProps {
  state: SearchState;
  /** The day picked now; when the results are for another day, the count line says which. */
  selectedDay: string | null;
  onRetry: () => void;
  /** Camera id -> name, for each card's time line. */
  cameraNames: ReadonlyMap<string, string>;
}

function countLine(count: number, day: string, selectedDay: string | null): string {
  const results = count === 1 ? '1 result' : `${count} results`;
  return day === selectedDay ? results : `${results} on ${formatShortDay(day)}`;
}

/** What was searched, from what the person picked and what the server knows: "Searched all 2 cameras on Fri 30 Oct". */
function scopeLine(camera: string, day: string, cameraNames: ReadonlyMap<string, string>): string {
  const when = formatShortDay(day);
  if (camera !== '') return `Searched ${cameraNames.get(camera) ?? camera} on ${when}`;
  const count = cameraNames.size;
  return count === 0 ? `Searched every camera on ${when}` : `Searched all ${count} camera${count === 1 ? '' : 's'} on ${when}`;
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
            <EmptyState title="No matching clips">
              No clips matched on {formatShortDay(state.day)}. Try other words or another day.
            </EmptyState>
          ) : (
            <p className="muted results-status__count">{countLine(clips.length, state.day, selectedDay)}</p>
          )}
          <p className="muted results-status__scope">{scopeLine(state.camera, state.day, cameraNames)}</p>
          {note ? <p className="muted">{note}</p> : null}
        </>
      );
      break;
    }
  }

  const clips = state.phase === 'done' ? state.response.clips : [];
  const proofs = state.phase === 'done' ? state.response.proofs : [];
  const needsIndexing = state.phase === 'done' ? state.response.needsIndexing : [];
  return (
    <>
      <div className="results-status" aria-live="polite">
        {status}
      </div>
      {state.phase === 'loading' ? <ClipListSkeleton /> : null}
      {state.phase === 'done'
        ? needsIndexing.map((item) => (
            <NeedsIndexingPanel key={`${state.question}|${state.day}|${item.noun}`} item={item} day={state.day} onDone={onRetry} />
          ))
        : null}
      {clips.length > 0 ? (
        <ul className="clip-list" aria-label="Results">
          {/* The best match leads, with its video and proof; the rest are compact rows. */}
          {clips.map((clip, index) =>
            index === 0 ? (
              <FeaturedClipCard
                key={clip.id}
                clip={clip}
                cameraName={cameraNames.get(clip.camera) ?? clip.camera}
                proof={proofs.find((p) => p.clipId === clip.id)}
              />
            ) : (
              <ClipCard
                key={clip.id}
                first={index === 1}
                clip={clip}
                cameraName={cameraNames.get(clip.camera) ?? clip.camera}
                proof={proofs.find((p) => p.clipId === clip.id)}
              />
            ),
          )}
        </ul>
      ) : null}
    </>
  );
}
