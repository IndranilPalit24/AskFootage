import { memo } from 'react';
import { Link } from 'react-router-dom';
import { CAMERA_STATUS_LABEL, CAMERA_STATUSES, isCameraStatus } from '../../api/cameraRules';
import type { Camera, CameraStatus } from '../../api/generated/types';
import { Icon } from '../../components/Icon';

export const OFFLINE_NOTE = 'Offline: no recordings to open';

const notSet = <span className="muted">Not set</span>;

function zoneText(count: number): string {
  if (count === 0) return 'No zones';
  return count === 1 ? '1 zone' : `${count} zones`;
}

interface RowProps {
  camera: Camera;
  onStatus: (camera: Camera, status: CameraStatus) => void;
  onDelete: (camera: Camera) => void;
}

const CameraRow = memo(function CameraRow({ camera, onStatus, onDelete }: RowProps) {
  const nameId = `camera-name-${camera.id}`;
  const noteId = `camera-note-${camera.id}`;
  const offline = camera.status === 'offline';

  return (
    <tr>
      <td className="num">{camera.id}</td>
      <td id={nameId}>{camera.name}</td>
      <td>{camera.location ?? notSet}</td>
      <td>{zoneText(camera.zoneCount)}</td>
      <td>{camera.department ?? notSet}</td>
      <td>
        <div className="cam-status">
          <span className="cam-status__badge">
            <span className={`cam-dot cam-dot--${camera.status}`} aria-hidden="true" />
            <span className="cam-status__label">{CAMERA_STATUS_LABEL[camera.status]}</span>
          </span>
          <select
            className="select"
            aria-label={`Status of ${camera.name}`}
            value={camera.status}
            onChange={(event) => {
              if (isCameraStatus(event.target.value)) onStatus(camera, event.target.value);
            }}
          >
            {CAMERA_STATUSES.map((status) => (
              <option key={status} value={status}>
                {CAMERA_STATUS_LABEL[status]}
              </option>
            ))}
          </select>
        </div>
      </td>
      <td>
        <div className="cam-actions">
          {offline ? (
            <>
              {/* aria-disabled keeps the button findable by keyboard and screen reader; it does nothing. */}
              <button type="button" className="btn btn--sm" aria-disabled="true" aria-describedby={`${nameId} ${noteId}`}>
                Recordings
              </button>
              <span id={noteId} className="row-note">
                {OFFLINE_NOTE}
              </span>
            </>
          ) : (
            <Link
              to={`/cameras/${encodeURIComponent(camera.id)}/recordings`}
              className="btn btn--sm"
              aria-describedby={nameId}
            >
              Recordings
            </Link>
          )}
          <button type="button" className="icon-btn" aria-label={`Delete ${camera.name}`} onClick={() => onDelete(camera)}>
            <Icon name="trash" />
          </button>
        </div>
      </td>
    </tr>
  );
});

interface TableProps {
  cameras: readonly Camera[];
  onStatus: (camera: Camera, status: CameraStatus) => void;
  onDelete: (camera: Camera) => void;
}

export function CameraTable({ cameras, onStatus, onDelete }: TableProps) {
  return (
    <div className="table-wrap">
      <table className="table table--cameras">
        <caption className="visually-hidden">Registered cameras</caption>
        <thead>
          <tr>
            <th scope="col">ID</th>
            <th scope="col">Name</th>
            <th scope="col">Location</th>
            <th scope="col">Zone</th>
            <th scope="col">Department</th>
            <th scope="col">Status</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {cameras.map((camera) => (
            <CameraRow key={camera.id} camera={camera} onStatus={onStatus} onDelete={onDelete} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
