import { useMemo, useState } from 'react';
import { useAppData } from '../app/AppDataContext';
import { useSearchActions, useSearchState } from '../app/SearchContext';
import { useSelectedDay } from '../app/SelectedDayContext';
import { usePageTitle } from '../hooks/usePageTitle';
import { AskBox } from '../features/search/AskBox';
import { SearchResults } from '../features/search/SearchResults';

// The ask box's shape while the days load; the word is announced, the shape is not.
const loading = (
  <div>
    <p className="visually-hidden" role="status">
      Loading…
    </p>
    <span className="skeleton skeleton--ask" aria-hidden="true" />
  </div>
);

/**
 * Before the first search the heading, ask box, examples and Day selector sit in the middle of the space
 * under the topbar, like a chat app's start screen; once someone searches they move to the top and the
 * results follow.
 */
export function FindFootageScreen() {
  usePageTitle('Find Footage');
  const { days, cameras } = useAppData();
  const { day, setDay } = useSelectedDay();
  const search = useSearchState();
  const { run } = useSearchActions();
  // One lookup table per camera list, not a scan per card.
  const cameraNames = useMemo(() => new Map((cameras ?? []).map((camera) => [camera.id, camera.name])), [cameras]);
  const started = search.phase !== 'idle';
  // The camera filter lives here, starting from the last search (so "Back to results" shows it again).
  const [camera, setCamera] = useState(() => (search.phase === 'idle' ? '' : search.camera));

  function submit(question: string) {
    if (day) run(question, day, camera);
  }

  function changeDay(next: string) {
    setDay(next);
    // Results always answer the day in the Day selector: ask the last question again for the new day.
    if (search.phase !== 'idle') run(search.question, next, camera);
  }

  function changeCamera(next: string) {
    setCamera(next);
    // The question stays in the box; an answered question is asked again for the new camera.
    if (search.phase !== 'idle') run(search.question, search.day, next);
  }

  function retry() {
    if (search.phase !== 'idle') run(search.question, search.day, search.camera);
  }

  return (
    <div className={started ? 'find' : 'find find--start'} data-testid="find-footage">
      <div className="find__group">
        <div className="page-head find__head">
          <div>
            <h1>Find Footage</h1>
            {started ? null : <p className="page-head__subtitle">Ask a question about your footage. Each result shows the proof.</p>}
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
            cameras={cameras ?? []}
            camera={camera}
            onCameraChange={changeCamera}
            busy={search.phase === 'loading'}
          />
        ) : (
          loading
        )}
      </div>
      <SearchResults state={search} selectedDay={day} onRetry={retry} cameraNames={cameraNames} />
    </div>
  );
}
