import { useState, type FormEvent } from 'react';
import { errorMessage } from '../../api/errors';
import { MAX_ZONE_POINTS, MIN_ZONE_POINTS, pointsLabel, ZONE_NAME_MAX } from './geometry';

interface NewZoneFormProps {
  pointCount: number;
  onUndo: () => void;
  onCancel: () => void;
  /** Creates the zone; a rejection is shown inline (for example "A zone called … already exists"). */
  onSave: (name: string) => Promise<void>;
}

/** The controls under the frame while a new zone is drawn: Undo point, Cancel, Zone name, Save zone. */
export function NewZoneForm({ pointCount, onUndo, onCancel, onSave }: NewZoneFormProps) {
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canSave = pointCount >= MIN_ZONE_POINTS && name.trim().length > 0 && !saving;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(name.trim());
    } catch (caught) {
      setError(errorMessage(caught));
      setSaving(false);
    }
  }

  let hint: string;
  if (pointCount >= MAX_ZONE_POINTS) hint = `${pointsLabel(pointCount)} (the most a zone can have).`;
  else if (pointCount < MIN_ZONE_POINTS) hint = `${pointsLabel(pointCount)}. A zone needs at least ${MIN_ZONE_POINTS}.`;
  else hint = `${pointsLabel(pointCount)}.`;

  return (
    <form className="zone-editor" aria-label="New zone" onSubmit={handleSubmit}>
      <p className="muted small" aria-live="polite">
        {hint}
      </p>
      <div className="zone-editor__controls">
        <div className="field">
          <label htmlFor="new-zone-name" className="field__label">
            Zone name
          </label>
          <input
            id="new-zone-name"
            className="input"
            type="text"
            required
            maxLength={ZONE_NAME_MAX}
            autoComplete="off"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div className="btn-row">
          <button type="button" className="btn" onClick={onUndo} disabled={pointCount === 0 || saving}>
            Undo point
          </button>
          <button type="button" className="btn" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
          <button type="submit" className="btn btn--primary" disabled={!canSave}>
            {saving ? 'Saving…' : 'Save zone'}
          </button>
        </div>
      </div>
      {error ? (
        <p className="inline-error" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
