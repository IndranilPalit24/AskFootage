import { memo, useState, type FormEvent } from 'react';
import { errorMessage } from '../../api/errors';
import type { Zone } from '../../api/generated/types';
import { ZONE_NAME_MAX } from './geometry';

type RowMode = 'view' | 'rename' | 'confirm-delete';

interface ZoneRowProps {
  zone: Zone;
  onRename: (zone: Zone, name: string) => Promise<void>;
  onDelete: (zone: Zone) => Promise<void>;
}

/** One zone: name and point count, with inline Rename (Save / Cancel) and Delete (Yes / No). */
function ZoneRow({ zone, onRename, onDelete }: ZoneRowProps) {
  const [mode, setMode] = useState<RowMode>('view');
  const [name, setName] = useState(zone.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputId = `zone-rename-${zone.id}`;

  function show(next: RowMode) {
    setMode(next);
    setError(null);
    setName(zone.name);
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      // A deleted row unmounts; a renamed one goes back to showing its name.
      setMode('view');
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  function handleRename(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    if (trimmed === zone.name) {
      setMode('view');
      return;
    }
    void run(() => onRename(zone, trimmed));
  }

  let body;
  if (mode === 'rename') {
    body = (
      <td colSpan={3}>
      <form className="zone-row zone-row--edit" aria-label={`Rename ${zone.name}`} onSubmit={handleRename}>
        <label htmlFor={inputId} className="visually-hidden">
          New name for {zone.name}
        </label>
        <input
          id={inputId}
          className="input zone-row__input"
          type="text"
          required
          maxLength={ZONE_NAME_MAX}
          autoComplete="off"
          // The person asked to rename: put them in the field.
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <div className="btn-row">
          <button type="submit" className="btn btn--primary" disabled={busy || name.trim().length === 0}>
            Save
          </button>
          <button type="button" className="btn" onClick={() => show('view')} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
      </td>
    );
  } else if (mode === 'confirm-delete') {
    body = (
      <td colSpan={3}>
      <div className="zone-row" role="group" aria-label={`Delete ${zone.name}`}>
        <span>Delete {zone.name}?</span>
        <div className="btn-row">
          <button type="button" className="btn btn--danger" onClick={() => void run(() => onDelete(zone))} disabled={busy}>
            Yes
          </button>
          <button type="button" className="btn" onClick={() => show('view')} disabled={busy}>
            No
          </button>
        </div>
      </div>
      </td>
    );
  } else {
    body = (
      <>
        <td className="zone-row__name">{zone.name}</td>
        <td className="num">{zone.points.length}</td>
        <td>
          <div className="btn-row">
            <button type="button" className="link-btn" aria-label={`Rename ${zone.name}`} onClick={() => show('rename')}>
              Rename
            </button>
            <button
              type="button"
              className="link-btn link-btn--danger"
              aria-label={`Delete ${zone.name}`}
              onClick={() => show('confirm-delete')}
            >
              Delete
            </button>
          </div>
        </td>
      </>
    );
  }

  return (
    <>
      <tr>{body}</tr>
      {error ? (
        <tr>
          <td colSpan={3}>
            <p className="inline-error" role="alert">
              {error}
            </p>
          </td>
        </tr>
      ) : null}
    </>
  );
}

interface ZoneListProps {
  zones: Zone[];
  onRename: (zone: Zone, name: string) => Promise<void>;
  onDelete: (zone: Zone) => Promise<void>;
}

const empty = <p className="muted">No zones yet. Use New zone to draw one on the frame.</p>;

/** Memoised: adding points to a new zone re-renders the screen, not this list. */
export const ZoneList = memo(function ZoneList({ zones, onRename, onDelete }: ZoneListProps) {
  if (zones.length === 0) return empty;
  return (
    <table className="table table--zones">
      <caption className="visually-hidden">Zones on this camera</caption>
      <thead>
        <tr>
          <th scope="col">Name</th>
          <th scope="col">Points</th>
          <th scope="col">
            <span className="visually-hidden">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {zones.map((zone) => (
          <ZoneRow key={zone.id} zone={zone} onRename={onRename} onDelete={onDelete} />
        ))}
      </tbody>
    </table>
  );
});
