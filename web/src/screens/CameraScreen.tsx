import { useCallback } from 'react';
import { Link } from 'react-router-dom';
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

export function CameraScreen() {
  const client = useApiClient();
  const { status, days, refreshDays } = useAppData();
  const { day, setDay } = useSelectedDay();
  const cameraId = status?.camera.id ?? null;
  const recordings = useAsyncData(
    day && cameraId ? () => client.listRecordings(day, cameraId) : null,
    ['recordings', day, cameraId],
  );

  const { reload } = recordings;
  const handleAdded = useCallback(() => {
    reload();
    refreshDays().catch(() => {
      // The day counts refresh on the next visit; the list itself already reloaded.
    });
  }, [reload, refreshDays]);

  if (!status || !days || !day || !cameraId) return loading;

  let summary = 'Loading recordings…';
  if (recordings.data) summary = recordingsSummary(recordings.data);
  else if (recordings.error) summary = '';

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Camera</h1>
          <p className="page-head__subtitle">{status.camera.name} · each day&apos;s recordings</p>
        </div>
        <AddRecordingButton day={day} camera={cameraId} onAdded={handleAdded} />
      </div>

      <DayStrip days={days} selected={day} onSelect={setDay} />

      <p className="summary" aria-live="polite">
        {summary}
      </p>

      <RecordingsTable
        caption={`Recordings on ${formatDayNoYear(day)}`}
        recordings={recordings.data}
        error={recordings.error?.message ?? null}
        onRetry={reload}
        openTo={FIND_FOOTAGE}
      />

      <p className="footnote">
        Ready recordings can be searched from Find Footage. <Link to={FIND_FOOTAGE}>Ask a question about this day</Link>
      </p>
    </>
  );
}
