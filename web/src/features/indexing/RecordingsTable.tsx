import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { Recording } from '../../api/generated/types';
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

function MessageRow({ children }: { children: ReactNode }) {
  return (
    <tr>
      <td colSpan={4} className="table__message">
        {children}
      </td>
    </tr>
  );
}

// Static rows, created once.
const loadingRow = <MessageRow>Loading recordings…</MessageRow>;
const emptyRow = <MessageRow>No recordings on this day.</MessageRow>;

/** Pill with a 6px dot; Ready uses the accent tint. */
function StatusChip({ status }: { status: Recording['status'] }) {
  return (
    <span className={status === 'ready' ? 'status status--ready' : 'status'}>
      <span className="status__dot" aria-hidden="true" />
      {STATUS_LABEL[status]}
    </span>
  );
}

/** Start time, Length, Status and an action per recording: Open when ready, otherwise a short note. */
export function RecordingsTable({ caption, recordings, error, onRetry, openTo }: RecordingsTableProps) {
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
    body = loadingRow;
  } else if (recordings.length === 0) {
    body = emptyRow;
  } else {
    body = recordings.map((recording) => {
      const startId = `rec-start-${recording.id}`;
      return (
        <tr key={recording.id}>
          <td id={startId} className="num">
            {recording.startTime}
          </td>
          <td className="num">{formatLength(recording.lengthSeconds)}</td>
          <td>
            <StatusChip status={recording.status} />
          </td>
          <td className="table__actions">
            {recording.status === 'ready' ? (
              <Link to={openTo} className="btn btn--sm" aria-describedby={startId}>
                Open
              </Link>
            ) : (
              <span className="row-note">{STATUS_NOTE[recording.status]}</span>
            )}
          </td>
        </tr>
      );
    });
  }

  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Start time</th>
            <th scope="col">Length</th>
            <th scope="col">Status</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
  );
}
