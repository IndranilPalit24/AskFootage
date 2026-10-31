import { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { Camera } from '../api/generated/types';
import { useApiClient } from '../app/ApiContext';
import { useAppData } from '../app/AppDataContext';
import { useSelectedDay } from '../app/SelectedDayContext';
import { AddRecordingButton } from '../features/indexing/AddRecordingButton';
import { DayStrip } from '../features/indexing/DayStrip';
import { RecordingsTable } from '../features/indexing/RecordingsTable';
import { recordingsSummary } from '../features/indexing/summary';
import { useAsyncData } from '../hooks/useAsyncData';
import { formatDayNoYear } from '../lib/dates';

// Find Footage reads the shared selected day, so this link is already scoped to the day shown here.
const FIND_FOOTAGE = '/';

const loading = (
  <p className="muted" role="status">
    Loading…
  </p>
);

const backLink = (
  <Link to="/cameras" className="back-link">
    <span aria-hidden="true">← </span>
    All cameras
  </Link>
);

/** One camera's recordings, day by day: the day strip, the summary line and the table, plus Add footage. */
function CameraRecordings({ camera }: { camera: Camera }) {
  const client = useApiClient();
  const { day, setDay } = useSelectedDay();
  // Both start at once: the recordings need the selected day, not this camera's day list.
  const days = useAsyncData(() => client.listDays(camera.id), ['days', camera.id]);
  const recordings = useAsyncData(
    day ? () => client.listRecordings(day, camera.id) : null,
    ['recordings', day, camera.id],
  );

  const reloadRecordings = recordings.reload;
  const reloadDays = days.reload;
  const handleAdded = useCallback(() => {
    reloadRecordings();
    reloadDays();
  }, [reloadRecordings, reloadDays]);

  if (!day) return loading;

  let summary = 'Loading recordings…';
  if (recordings.data) summary = recordingsSummary(recordings.data);
  else if (recordings.error) summary = '';

  return (
    <>
      {backLink}
      <div className="page-head">
        <div>
          <h1>Recordings</h1>
          <p className="page-head__subtitle">{camera.name} · each day&apos;s recordings</p>
        </div>
        <AddRecordingButton day={day} camera={camera.id} onAdded={handleAdded} />
      </div>

      {days.data ? <DayStrip days={days.data} selected={day} onSelect={setDay} /> : null}

      <p className="summary" aria-live="polite">
        {summary}
      </p>

      <RecordingsTable
        caption={`Recordings on ${formatDayNoYear(day)}`}
        recordings={recordings.data}
        error={recordings.error?.message ?? null}
        onRetry={reloadRecordings}
        openTo={FIND_FOOTAGE}
      />

      <p className="footnote">
        Ready recordings can be searched from Find Footage. <Link to={FIND_FOOTAGE}>Ask a question about this day</Link>
      </p>
    </>
  );
}

export function CameraRecordingsScreen() {
  const { id = '' } = useParams();
  const client = useApiClient();
  const { cameras } = useAppData();
  const listed = cameras?.find((camera) => camera.id === id) ?? null;
  // Not in the list this page has (it may be a few seconds old): ask the server about this one camera.
  const fetched = useAsyncData(cameras && !listed ? () => client.getCamera(id) : null, ['camera', id]);
  const camera = listed ?? fetched.data ?? null;

  if (camera) return <CameraRecordings key={camera.id} camera={camera} />;
  if (!cameras || !fetched.error) return loading;

  // An unknown or malformed id is "not found" to the person, whatever code the server used.
  const missing = fetched.error.code === 'not_found' || fetched.error.code === 'validation_error';
  return (
    <div className="stack">
      {backLink}
      {missing ? (
        <>
          <h1>Camera not found.</h1>
          <p className="muted">It may have been deleted. Pick a camera from the list.</p>
        </>
      ) : (
        <div role="alert">
          <p className="error-text">{fetched.error.message}</p>
          <p className="results-status__action">
            <button type="button" className="btn" onClick={fetched.reload}>
              Try again
            </button>
          </p>
        </div>
      )}
    </div>
  );
}
