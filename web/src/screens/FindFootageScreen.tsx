import { useMemo } from 'react';
import { useAppData } from '../app/AppDataContext';
import { useSearchActions, useSearchState } from '../app/SearchContext';
import { useSelectedDay } from '../app/SelectedDayContext';
import { AskBox } from '../features/search/AskBox';
import { SearchResults } from '../features/search/SearchResults';

const loading = (
  <p className="muted" role="status">
    Loading…
  </p>
);

/**
 * Before the first search the heading, ask box, examples and Day selector sit in the middle of the space
 * under the topbar, like a chat app's start screen; once someone searches they move to the top and the
 * results follow.
 */
export function FindFootageScreen() {
  const { days, cameras } = useAppData();
  const { day, setDay } = useSelectedDay();
  const search = useSearchState();
  const { run } = useSearchActions();
  // One lookup table per camera list, not a scan per card.
  const cameraNames = useMemo(() => new Map((cameras ?? []).map((camera) => [camera.id, camera.name])), [cameras]);
  const started = search.phase !== 'idle';

  function submit(question: string) {
    if (day) run(question, day);
  }

  function changeDay(next: string) {
    setDay(next);
    // Results always answer the day in the Day selector: ask the last question again for the new day.
    if (search.phase !== 'idle') run(search.question, next);
  }

  function retry() {
    if (search.phase !== 'idle') run(search.question, search.day);
  }

  return (
    <div className={started ? 'find' : 'find find--start'} data-testid="find-footage">
      <div className="find__group">
        <div className="page-head find__head">
          <div>
            <h1>Find Footage</h1>
            <p className="page-head__subtitle">Ask a question about your footage. Each result shows the proof.</p>
          </div>
        </div>
        {days && day ? (
          <AskBox
            // Coming back to this screen ("Back to results") shows the last question again.
            initialQuestion={search.phase === 'idle' ? '' : search.question}
            onSubmit={submit}
            days={days}
            day={day}
            onDayChange={changeDay}
          />
        ) : (
          loading
        )}
      </div>
      <SearchResults state={search} selectedDay={day} onRetry={retry} cameraNames={cameraNames} />
    </div>
  );
}
