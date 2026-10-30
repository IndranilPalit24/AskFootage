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

export function FindFootageScreen() {
  const { status, days } = useAppData();
  const { day, setDay } = useSelectedDay();
  const search = useSearchState();
  const { run } = useSearchActions();

  function submit(question: string) {
    if (day) run(question, day);
  }

  function changeDay(next: string) {
    setDay(next);
    // Results always answer the day in the scope line: ask the last question again for the new day.
    if (search.phase !== 'idle') run(search.question, next);
  }

  function retry() {
    if (search.phase !== 'idle') run(search.question, search.day);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Find Footage</h1>
          <p className="page-head__subtitle">Ask a question about your footage. Each result shows the proof.</p>
        </div>
      </div>
      {status && days && day ? (
        <AskBox
          // Coming back to this screen ("Back to results") shows the last question again.
          initialQuestion={search.phase === 'idle' ? '' : search.question}
          onSubmit={submit}
          days={days}
          day={day}
          onDayChange={changeDay}
          cameraName={status.camera.name}
        />
      ) : (
        loading
      )}
      <SearchResults state={search} selectedDay={day} onRetry={retry} />
    </>
  );
}
