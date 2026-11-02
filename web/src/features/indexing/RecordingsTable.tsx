import type { ReactNode } from 'react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useApiClient } from '../../app/ApiContext';
import type { Recording } from '../../api/generated/types';
import { Pager, usePaging } from '../../components/Pager';
import { TableSkeletonRows } from '../../components/Skeletons';
import { formatLength } from '../../lib/time';
import { STATUS_LABEL, STATUS_NOTE } from './summary';

interface RecordingsTableProps {
  caption: string;
  recordings: Recording[] | undefined;
  error: string | null;
  onRetry: () => void;
  /** Where a ready row's Open goes: Find Footage, which is already scoped to the selected day. */
  openTo: string;
}

/** A recording's poster, when the server has one; a failed image is dropped, not shown broken. */
function RowPoster({ path }: { path: string }) {
  const client = useApiClient();
  const url = client.assetUrl(path);
  const [failed, setFailed] = useState<string | null>(null);
  if (failed === url) return <span className="table__poster" aria-hidden="true" />;
  return <img className="table__poster" src={url} alt="" loading="lazy" width={64} height={36} onError={() => setFailed(url)} />;
}

function MessageRow({ children }: { children: ReactNode }) {
  return (
    <tr>
      <td colSpan={4} className="table__message">
        {children}
      </td>
    </tr>
  );
}

// Static rows, created once. The loading text stays in the DOM (hidden) so it is announced; the shapes are skeletons.
const loadingRows = (
  <>
    <tr>
      <td colSpan={4} className="table__message">
        <span className="visually-hidden">Loading recordings…</span>
        <span className="skeleton skeleton--line" aria-hidden="true" />
      </td>
    </tr>
    <TableSkeletonRows columns={4} rows={2} />
  </>
);
const emptyRow = (
  <MessageRow>
    <span>No recordings on this day.</span> <span className="row-note">Pick another day above, or use Add footage.</span>
  </MessageRow>
);

/** A status dot (green ready, amber in progress, grey waiting) and its word: the colour is never alone. */
function StatusChip({ status }: { status: Recording['status'] }) {
  return (
    <span className={status === 'ready' ? 'status status--ready' : 'status'} data-status={status}>
      <span className="status__dot" aria-hidden="true" />
      {STATUS_LABEL[status]}
    </span>
  );
}

/** What a ready recording without a video shows in place of Open. */
export const FOOTAGE_NOT_INCLUDED_NOTE = 'Footage not included in this demo build';

const NO_ROWS: readonly Recording[] = [];

/**
 * Start time, Length, Status and an action per recording: Open when ready and it has footage, a quiet note when
 * it has none, otherwise the status note. Long days are paged (50 rows at a time).
 */
export function RecordingsTable({ caption, recordings, error, onRetry, openTo }: RecordingsTableProps) {
  const paging = usePaging(recordings ?? NO_ROWS);
  let body: ReactNode;
  if (error) {
    body = (
      <MessageRow>
        <span className="error-text" role="alert">
          {error}
        </span>{' '}
        <button type="button" className="btn btn--sm" onClick={onRetry}>
          Try again
        </button>
      </MessageRow>
    );
  } else if (!recordings) {
    body = loadingRows;
  } else if (recordings.length === 0) {
    body = emptyRow;
  } else {
    body = paging.rows.map((recording) => {
      const startId = `rec-start-${recording.id}`;
      // hasFootage false: listed and counted, but no video behind it, so nothing links to a player.
      const playable = recording.status === 'ready' && recording.hasFootage !== false;
      return (
        <tr key={recording.id}>
          <td id={startId} className="cell-id">
            <div className="row-start">
              {recording.posterUrl ? <RowPoster path={recording.posterUrl} /> : null}
              {playable ? (
                <Link to={`/recordings/${encodeURIComponent(recording.id)}`} aria-label={`Watch the recording from ${recording.startTime}`}>
                  {recording.startTime}
                </Link>
              ) : (
                recording.startTime
              )}
            </div>
          </td>
          <td className="cell-num">{formatLength(recording.lengthSeconds)}</td>
          <td>
            <StatusChip status={recording.status} />
          </td>
          <td className="table__actions">
            <span className="row-actions">
              {playable ? (
                <Link to={openTo} className="btn btn--sm" aria-describedby={startId}>
                  Open
                </Link>
              ) : (
                <span className="row-note">
                  {recording.status === 'ready' ? FOOTAGE_NOT_INCLUDED_NOTE : STATUS_NOTE[recording.status]}
                </span>
              )}
            </span>
          </td>
        </tr>
      );
    });
  }

  return (
    <>
    <div className="table-wrap">
      <table className="table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Start time</th>
            <th scope="col" className="cell-num">
              Length
            </th>
            <th scope="col">Status</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    <Pager paging={paging} noun="recordings" />
    </>
  );
}
