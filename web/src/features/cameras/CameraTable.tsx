import { memo } from 'react';
import { Link } from 'react-router-dom';
import { CAMERA_STATUS_LABEL, CAMERA_STATUSES } from '../../api/cameraRules';
import type { Camera, CameraStatus } from '../../api/generated/types';
import { ActionMenu, type MenuAction } from '../../components/ActionMenu';
import { Icon } from '../../components/Icon';
import { Pager, usePaging } from '../../components/Pager';

export const OFFLINE_NOTE = 'Offline: no recordings to open';

const notSet = <span className="muted">Not set</span>;

interface RowProps {
  camera: Camera;
  onStatus: (camera: Camera, status: CameraStatus) => void;
  onDelete: (camera: Camera) => void;
}

const CameraRow = memo(function CameraRow({ camera, onStatus, onDelete }: RowProps) {
  const nameId = `camera-name-${camera.id}`;
  const noteId = `camera-note-${camera.id}`;
  const offline = camera.status === 'offline';
  // Set the status to one of the others, or delete: all from one menu.
  const items: MenuAction[] = [
    ...CAMERA_STATUSES.filter((status) => status !== camera.status).map((status) => ({
      label: `Mark ${CAMERA_STATUS_LABEL[status].toLowerCase()}`,
      onSelect: () => onStatus(camera, status),
    })),
    { label: `Delete ${camera.name}`, onSelect: () => onDelete(camera), danger: true },
  ];

  return (
    <tr>
      <td className="cell-id">{camera.id}</td>
      <td id={nameId}>{camera.name}</td>
      <td>{camera.location ?? notSet}</td>
      <td>{camera.department ?? notSet}</td>
      <td>
        <span className="cam-status__badge">
          <span className={`cam-dot cam-dot--${camera.status}`} aria-hidden="true" />
          <span className="cam-status__label">{CAMERA_STATUS_LABEL[camera.status]}</span>
        </span>
      </td>
      <td>
        <div className="cam-actions row-actions">
          {offline ? (
            <>
              {/* aria-disabled keeps the link findable by keyboard and screen reader; it does nothing. */}
              <button type="button" className="link-btn" aria-disabled="true" aria-describedby={`${nameId} ${noteId}`}>
                Recordings
              </button>
              <span id={noteId} className="row-note">
                {OFFLINE_NOTE}
              </span>
            </>
          ) : (
            <Link to={`/cameras/${encodeURIComponent(camera.id)}/recordings`} className="link-btn" aria-describedby={nameId}>
              Recordings
            </Link>
          )}
          <ActionMenu
            label={`Actions for ${camera.name}`}
            triggerLabel={`Actions for ${camera.name}`}
            triggerClassName="icon-btn"
            trigger={<Icon name="kebab" />}
            items={items}
          />
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
  const paging = usePaging(cameras);
  return (
    <>
    <div className="table-wrap">
      <table className="table table--cameras">
        <caption className="visually-hidden">Registered cameras</caption>
        <thead>
          <tr>
            <th scope="col">ID</th>
            <th scope="col">Name</th>
            <th scope="col">Location</th>
            <th scope="col">Department</th>
            <th scope="col">Status</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {paging.rows.map((camera) => (
            <CameraRow key={camera.id} camera={camera} onStatus={onStatus} onDelete={onDelete} />
          ))}
        </tbody>
      </table>
    </div>
    <Pager paging={paging} noun="cameras" />
    </>
  );
}
