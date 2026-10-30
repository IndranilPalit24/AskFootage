import { useCallback, useState } from 'react';
import type { Point, Zone } from '../api/generated/types';
import { useApiClient } from '../app/ApiContext';
import { useAppData } from '../app/AppDataContext';
import { MAX_ZONE_POINTS, sortZones } from '../features/zones/geometry';
import { NewZoneForm } from '../features/zones/NewZoneForm';
import { ZoneFrame } from '../features/zones/ZoneFrame';
import { ZoneList } from '../features/zones/ZoneList';
import { useAsyncData } from '../hooks/useAsyncData';

const INSTRUCTIONS_ID = 'zone-draw-instructions';

const loading = (
  <p className="muted" role="status">
    Loading…
  </p>
);

const loadingZones = (
  <p className="muted" role="status">
    Loading zones…
  </p>
);

export function ZonesScreen() {
  const client = useApiClient();
  const { status } = useAppData();
  const cameraId = status?.camera.id ?? null;
  const zones = useAsyncData(cameraId ? () => client.listZones(cameraId) : null, ['zones', cameraId]);
  // null: not drawing. An array: the points of the zone being drawn, in click order.
  const [draft, setDraft] = useState<Point[] | null>(null);

  const { mutate } = zones;

  const addPoint = useCallback((point: Point) => {
    setDraft((current) => (current && current.length < MAX_ZONE_POINTS ? [...current, point] : current));
  }, []);

  async function createZone(name: string) {
    if (!cameraId || !draft) return;
    const zone = await client.createZone({ camera: cameraId, name, points: draft });
    mutate((current) => sortZones([...current, zone]));
    setDraft(null);
  }

  const renameZone = useCallback(
    async (zone: Zone, name: string) => {
      // PUT replaces the whole zone, so the points go along unchanged.
      const updated = await client.replaceZone(zone.id, { name, points: zone.points });
      mutate((current) => sortZones(current.map((item) => (item.id === updated.id ? updated : item))));
    },
    [client, mutate],
  );

  const deleteZone = useCallback(
    async (zone: Zone) => {
      await client.deleteZone(zone.id);
      mutate((current) => current.filter((item) => item.id !== zone.id));
    },
    [client, mutate],
  );

  if (!status) {
    return loading;
  }

  const drawing = draft !== null;
  const list = zones.data ?? [];

  let listBody;
  if (zones.error && !zones.data) {
    listBody = (
      <div role="alert">
        <p className="error-text">{zones.error.message}</p>
        <p className="results-status__action">
          <button type="button" className="btn" onClick={zones.reload}>
            Try again
          </button>
        </p>
      </div>
    );
  } else if (!zones.data) {
    listBody = loadingZones;
  } else {
    listBody = <ZoneList zones={list} onRename={renameZone} onDelete={deleteZone} />;
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Zones</h1>
          <p className="page-head__subtitle">
            Mark areas of the camera view. Questions can name them, e.g. &ldquo;anyone in the loading door&rdquo;.
          </p>
        </div>
      </div>

      <div className="zones-grid">
        <section className="card card--padded" aria-labelledby="frame-heading">
          <div className="section-header">
            <h2 id="frame-heading">{drawing ? 'Draw a new zone' : 'Camera view'}</h2>
            {drawing ? null : (
              <button type="button" className="btn btn--primary" onClick={() => setDraft([])}>
                New zone
              </button>
            )}
          </div>
          <ZoneFrame
            zones={list}
            caption={`${status.camera.name} · still frame`}
            drawing={drawing}
            draft={draft ?? []}
            onAddPoint={addPoint}
            instructionsId={INSTRUCTIONS_ID}
          />
          {drawing ? (
            <>
              <p id={INSTRUCTIONS_ID} className="muted small zone-editor__help">
                Click the frame to add each corner. With a keyboard: focus the frame, move the cursor with the arrow
                keys (Shift for bigger steps) and press Enter to add a point.
              </p>
              <NewZoneForm
                pointCount={draft.length}
                onUndo={() => setDraft((current) => (current ? current.slice(0, -1) : current))}
                onCancel={() => setDraft(null)}
                onSave={createZone}
              />
            </>
          ) : null}
        </section>

        <section className="card card--padded" aria-labelledby="zone-list-heading">
          <h2 id="zone-list-heading" className="section-title">
            Zones on this camera
          </h2>
          {listBody}
        </section>
      </div>
    </>
  );
}
