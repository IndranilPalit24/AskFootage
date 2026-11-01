import { useCallback, useMemo, useState } from 'react';
import { byCameraId, CAMERA_STATUS_LABEL } from '../api/cameraRules';
import { ApiError, errorMessage } from '../api/errors';
import type { Camera, CameraStatus } from '../api/generated/types';
import { useApiClient } from '../app/ApiContext';
import { useAppData } from '../app/AppDataContext';
import { useToasts } from '../app/ToastContext';
import { Modal } from '../components/Modal';
import { Tabs, type TabDef } from '../components/Tabs';
import { AddCameraForm } from '../features/cameras/AddCameraForm';
import { CameraTable } from '../features/cameras/CameraTable';
import { useCameraSync } from '../features/cameras/useCameraSync';

const REGISTRY = 'registry';
const ADD = 'add';

const loading = (
  <p className="muted" role="status">
    Loading cameras…
  </p>
);

const empty = <p className="muted">No cameras yet. Add one in the Add new camera tab.</p>;

interface Counts {
  total: number;
  online: number;
  standby: number;
  offline: number;
}

/** One pass over the list. */
function countStatuses(cameras: readonly Camera[]): Counts {
  const counts: Counts = { total: cameras.length, online: 0, standby: 0, offline: 0 };
  for (const camera of cameras) counts[camera.status] += 1;
  return counts;
}

function SummaryCards({ counts }: { counts: Counts }) {
  const cards: Array<[string, number]> = [
    ['Total cameras', counts.total],
    ['Online', counts.online],
    ['Standby', counts.standby],
    ['Offline/Error', counts.offline],
  ];
  return (
    <section aria-label="Camera summary">
      <dl className="cam-cards">
        {cards.map(([label, value]) => (
          <div key={label} className="card card--padded cam-card">
            <dt className="muted small">{label}</dt>
            <dd className="cam-card__value num">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function replaceCamera(list: Camera[], camera: Camera): Camera[] {
  return list.map((item) => (item.id === camera.id ? camera : item));
}

/** Puts a camera back in id order, unless the list already has it. */
function withCamera(list: Camera[], camera: Camera): Camera[] {
  return list.some((item) => item.id === camera.id) ? list : [...list, camera].toSorted(byCameraId);
}

/** The one open delete dialog: first a plain confirmation, then (if the server says it has recordings) a second. */
interface DeletePrompt {
  camera: Camera;
  deleteRecordings: boolean;
  message: string;
}

export function CamerasScreen() {
  const client = useApiClient();
  const toasts = useToasts();
  const { cameras, setCameras } = useAppData();
  const { refreshFailed, write } = useCameraSync(client, setCameras);
  const [tab, setTab] = useState(REGISTRY);
  const [prompt, setPrompt] = useState<DeletePrompt | null>(null);

  const counts = useMemo(() => countStatuses(cameras ?? []), [cameras]);

  const changeStatus = useCallback(
    async (camera: Camera, status: CameraStatus) => {
      if (camera.status === status) return;
      const previous = camera.status;
      setCameras((list) => replaceCamera(list, { ...camera, status }));
      try {
        const updated = await write(() => client.updateCamera(camera.id, { status }));
        setCameras((list) => replaceCamera(list, updated));
        toasts.success(`${camera.name} is now ${CAMERA_STATUS_LABEL[updated.status]}.`);
      } catch (caught) {
        setCameras((list) => replaceCamera(list, { ...camera, status: previous }));
        toasts.error(`Could not change the status of ${camera.name}. ${errorMessage(caught)}`);
      }
    },
    [client, setCameras, toasts, write],
  );

  const deleteCamera = useCallback(
    async (camera: Camera, deleteRecordings: boolean) => {
      // The row goes at once; it comes back if the server refuses.
      setCameras((list) => list.filter((item) => item.id !== camera.id));
      try {
        await write(() =>
          deleteRecordings ? client.deleteCamera(camera.id, { deleteRecordings: true }) : client.deleteCamera(camera.id),
        );
        toasts.success(deleteRecordings ? `Deleted ${camera.name} and its recordings.` : `Deleted ${camera.name}.`);
      } catch (caught) {
        setCameras((list) => withCamera(list, camera));
        if (!deleteRecordings && caught instanceof ApiError && caught.code === 'camera_has_recordings') {
          setPrompt({ camera, deleteRecordings: true, message: caught.message });
        } else {
          toasts.error(`Could not delete ${camera.name}. ${errorMessage(caught)}`);
        }
      }
    },
    [client, setCameras, toasts, write],
  );

  const askToDelete = useCallback(
    (camera: Camera) =>
      setPrompt({ camera, deleteRecordings: false, message: 'The camera will be removed from the registry.' }),
    [],
  );

  const added = useCallback(
    (camera: Camera) => {
      setCameras((list) => withCamera(list, camera));
      setTab(REGISTRY);
    },
    [setCameras],
  );

  let registry;
  if (!cameras) {
    registry = loading;
  } else {
    registry = (
      <div className="stack">
        <SummaryCards counts={counts} />
        {refreshFailed ? (
          <p className="muted small" role="status">
            Could not refresh. Retrying.
          </p>
        ) : null}
        {cameras.length === 0 ? empty : <CameraTable cameras={cameras} onStatus={changeStatus} onDelete={askToDelete} />}
      </div>
    );
  }

  const tabs: TabDef[] = [
    { id: REGISTRY, label: 'Camera registry', panel: registry },
    {
      id: ADD,
      label: 'Add new camera',
      panel: <AddCameraForm cameraCount={cameras?.length ?? 0} write={write} onAdded={added} />,
    },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Cameras</h1>
          <p className="page-head__subtitle">Register cameras, set their status and open their recordings.</p>
        </div>
      </div>
      <Tabs label="Cameras" tabs={tabs} selected={tab} onSelect={setTab} />
      {prompt ? (
        <Modal
          title={prompt.deleteRecordings ? `${prompt.camera.name} has recordings` : `Delete ${prompt.camera.name}?`}
          onClose={() => setPrompt(null)}
          actions={
            <>
              <button type="button" className="btn" data-autofocus onClick={() => setPrompt(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn--danger"
                onClick={() => {
                  setPrompt(null);
                  void deleteCamera(prompt.camera, prompt.deleteRecordings);
                }}
              >
                {prompt.deleteRecordings ? 'Delete camera and its recordings' : 'Delete'}
              </button>
            </>
          }
        >
          <p>{prompt.message}</p>
        </Modal>
      ) : null}
    </>
  );
}
