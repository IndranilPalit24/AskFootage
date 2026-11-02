import { useCallback, useState, type KeyboardEvent } from 'react';
import { Link } from 'react-router-dom';
import type { Point, Zone } from '../api/generated/types';
import { useApiClient } from '../app/ApiContext';
import { useAppData } from '../app/AppDataContext';
import { MAX_ZONE_POINTS, sortZones } from '../features/zones/geometry';
import { NewZoneForm } from '../features/zones/NewZoneForm';
import { ZoneFrame } from '../features/zones/ZoneFrame';
import { ZoneList } from '../features/zones/ZoneList';
import { Icon } from '../components/Icon';
import { EmptyState } from '../components/EmptyState';
import { useSelectedDay } from '../app/SelectedDayContext';
import { useAsyncData } from '../hooks/useAsyncData';
import { usePageTitle } from '../hooks/usePageTitle';

const INSTRUCTIONS_ID = 'zone-draw-instructions';

const loading = (
  <p className="muted" role="status">
    Loading…
  </p>
);

const loadingZones = (
  <div>
    <p className="visually-hidden" role="status">
      Loading zones…
    </p>
    <div className="stack stack--tight" aria-hidden="true">
      <span className="skeleton skeleton--line" />
      <span className="skeleton skeleton--line skeleton--short" />
    </div>
  </div>
);

export function ZonesScreen() {
  usePageTitle('Zones');
  const client = useApiClient();
  const { cameras } = useAppData();
  const { day } = useSelectedDay();
  const [chosenCamera, setChosenCamera] = useState<string | null>(null);
  // Derived, not synced: the picked camera while it exists, otherwise the first one.
  // With no pick yet, a camera that has a real still frame to draw on comes first.
  const withStill = useAsyncData(day ? () => client.listRecordings(day) : null, ['zone-default-camera', day]);
  const stillCamera = withStill.data?.find((recording) => recording.posterUrl !== null)?.camera;
  const camera =
    cameras?.find((item) => item.id === chosenCamera) ?? cameras?.find((item) => item.id === stillCamera) ?? cameras?.[0] ?? null;
  const cameraId = camera?.id ?? null;
  const zones = useAsyncData(cameraId ? () => client.listZones(cameraId) : null, ['zones', cameraId]);
  // The still frame to draw on: a poster of this camera's footage on the selected day, when there is any.
  const stills = useAsyncData(cameraId && day ? () => client.listRecordings(day, cameraId) : null, ['zone-still', cameraId, day]);
  const stillPath = stills.data?.find((recording) => recording.posterUrl !== null)?.posterUrl ?? null;
  const stillUrl = stillPath === null ? null : client.assetUrl(stillPath);
  // null: not drawing. An array: the points of the zone being drawn, in click order.
  const [draft, setDraft] = useState<Point[] | null>(null);

  function pickCamera(id: string) {
    setChosenCamera(id);
    // A half-drawn zone belongs to the other camera's view.
    setDraft(null);
  }

  const { mutate } = zones;

  const addPoint = useCallback((point: Point) => {
    setDraft((current) => (current && current.length < MAX_ZONE_POINTS ? [...current, point] : current));
  }, []);

  // Double click: the corners are done. The two clicks of the double click each added a point; drop the repeat,
  // then go to the name field.
  function finishDraft() {
    setDraft((current) => {
      if (!current || current.length < 2) return current;
      const [lastX, lastY] = current[current.length - 1]!;
      const [prevX, prevY] = current[current.length - 2]!;
      return Math.abs(lastX - prevX) < 0.01 && Math.abs(lastY - prevY) < 0.01 ? current.slice(0, -1) : current;
    });
    document.getElementById('new-zone-name')?.focus();
  }

  function handleEscape(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape' && draft !== null) {
      event.preventDefault();
      setDraft(null);
    }
  }

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

  if (!cameras) {
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

  const pageHead = (
    <div className="page-head">
      <h1>Zones</h1>
      {camera && !drawing ? (
        <button type="button" className="btn btn--primary" onClick={() => setDraft([])}>
          <Icon name="plus" size={16} />
          New zone
        </button>
      ) : null}
    </div>
  );

  if (!camera) {
    return (
      <>
        {pageHead}
        <EmptyState
          title="No cameras to draw on yet"
          action={
            <Link to="/cameras" className="btn btn--primary">
              Add a camera
            </Link>
          }
        >
          Zones are drawn on a camera&apos;s view. Add a camera first, then come back to mark an area.
        </EmptyState>
      </>
    );
  }

  return (
    <div className="screen--wide">
      {pageHead}

      <div className="field field--inline zones-camera">
        <label htmlFor="zones-camera" className="field__label">
          Camera
        </label>
        <select id="zones-camera" className="select" value={camera.id} onChange={(event) => pickCamera(event.target.value)}>
          {cameras.map((item) => (
            <option key={item.id} value={item.id}>
              {item.id} - {item.name}
            </option>
          ))}
        </select>
      </div>

      <div className="zones-grid" onKeyDown={handleEscape}>
        <section className="zones-main" aria-label="Camera view">
          <ZoneFrame
            zones={list}
            caption={`${camera.id} - ${camera.name}`}
            drawing={drawing}
            draft={draft ?? []}
            onAddPoint={addPoint}
            onFinish={finishDraft}
            instructionsId={INSTRUCTIONS_ID}
            imageUrl={stillUrl}
          />
          <p id={INSTRUCTIONS_ID} className="zone-hint">
            <Icon name="cursor" size={16} />
            {drawing
              ? 'Click to add points. Double click to finish. Escape cancels. A zone needs at least 3 points. With a keyboard: focus the frame, move the cursor with the arrow keys (Shift for bigger steps) and press Enter to add a point.'
              : 'Click New zone, then click the picture to add points and draw a zone. Double click to finish.'}
          </p>
          {drawing ? (
            <NewZoneForm
              pointCount={draft.length}
              onUndo={() => setDraft((current) => (current ? current.slice(0, -1) : current))}
              onCancel={() => setDraft(null)}
              onSave={createZone}
            />
          ) : null}
        </section>

        <section className="card card--padded zones-side" aria-labelledby="zone-list-heading">
          <h2 id="zone-list-heading" className="section-title">
            Zones on this camera
          </h2>
          {listBody}
        </section>
      </div>
    </div>
  );
}
