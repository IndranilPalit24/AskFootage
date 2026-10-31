import { Link } from 'react-router-dom';
import { CAMERA_STATUS_LABEL } from '../api/cameraRules';
import type { Camera } from '../api/generated/types';
import { useAppData } from '../app/AppDataContext';

// Read-only for now: adding, editing and deleting cameras is deferred. The list comes from the app's boot
// data, whose load error the shell already shows with Try again.

const loading = (
  <p className="muted" role="status">
    Loading cameras…
  </p>
);

const empty = <p className="muted">No cameras yet.</p>;

/** Pill with a dot; Online uses the accent tint, like a ready recording. */
function CameraStatusChip({ status }: { status: Camera['status'] }) {
  return (
    <span className={status === 'online' ? 'status status--ready' : 'status'}>
      <span className="status__dot" aria-hidden="true" />
      {CAMERA_STATUS_LABEL[status]}
    </span>
  );
}

function CameraRow({ camera }: { camera: Camera }) {
  return (
    <tr>
      <td>
        <Link to={`/cameras/${encodeURIComponent(camera.id)}/recordings`}>{camera.name}</Link>
      </td>
      <td>
        <CameraStatusChip status={camera.status} />
      </td>
      <td>{camera.location ?? <span className="muted">Not set</span>}</td>
    </tr>
  );
}

export function CamerasScreen() {
  const { cameras } = useAppData();

  let body;
  if (!cameras) {
    body = loading;
  } else if (cameras.length === 0) {
    body = empty;
  } else {
    body = (
      <div className="table-wrap">
        <table className="table">
          <caption className="visually-hidden">Cameras</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Status</th>
              <th scope="col">Location</th>
            </tr>
          </thead>
          <tbody>
            {cameras.map((camera) => (
              <CameraRow key={camera.id} camera={camera} />
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Cameras</h1>
          <p className="page-head__subtitle">Pick a camera to see its recordings.</p>
        </div>
      </div>
      {body}
    </>
  );
}
