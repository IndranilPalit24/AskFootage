import { memo, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../../api/errors';
import type { SavedClip } from '../../api/generated/types';
import { useApiClient } from '../../app/ApiContext';
import { ClipThumb, clipPosterPath } from '../../components/ClipThumb';
import { Icon } from '../../components/Icon';
import { formatFullDay } from '../../lib/dates';
import { clipDuration, formatClock } from '../../lib/time';

/** The note limit in the UI. The contract allows 500; see data/specs/needs-note-limit.md. */
export const NOTE_MAX = 200;
const NOTE_SAVED_FLASH_MS = 2000;

interface SavedClipRowProps {
  saved: SavedClip;
  onSaveNote: (saved: SavedClip, note: string) => Promise<void>;
  onRemove: (saved: SavedClip) => Promise<void>;
  /** The clip's camera name, when the camera list knows it. */
  cameraName?: string;
}

/** One saved clip: still, label, day and time, an editable note (Save note), Open and Remove. */
export const SavedClipRow = memo(function SavedClipRow({ saved, onSaveNote, onRemove, cameraName }: SavedClipRowProps) {
  const { clip } = saved;
  const client = useApiClient();
  const posterPath = clipPosterPath(clip);
  const [note, setNote] = useState(saved.note);
  const [busy, setBusy] = useState<'note' | 'remove' | null>(null);
  const [flash, setFlash] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const labelId = `saved-label-${saved.id}`;
  const noteId = `saved-note-${saved.id}`;
  const counterId = `saved-count-${saved.id}`;

  useEffect(() => {
    if (!flash) return undefined;
    const timer = window.setTimeout(() => setFlash(false), NOTE_SAVED_FLASH_MS);
    return () => window.clearTimeout(timer);
  }, [flash]);

  async function act(kind: 'note' | 'remove', action: () => Promise<void>) {
    if (busy) return;
    setBusy(kind);
    setError(null);
    setFlash(false);
    try {
      await action();
      if (kind === 'note') setFlash(true);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <li>
      <article className="card saved-row" aria-labelledby={labelId}>
        <ClipThumb
          shape="four-three"
          url={posterPath === null ? null : client.assetUrl(posterPath)}
          duration={formatClock(clipDuration(clip))}
        />
        <div className="saved-row__info">
          <h2 id={labelId} className="clip-card__label" title={clip.label}>
            {clip.label}
          </h2>
          <p className="clip-card__time">
            {formatFullDay(clip.day)}, {clip.startTime.slice(0, 5)}
          </p>
          <p className="clip-card__time">
            <span className="mono">{clip.camera}</span> {cameraName ?? ''}
          </p>
          <p className="clip-card__reason">{clip.whyMatched}</p>
        </div>
        <div className="saved-row__note">
          <label htmlFor={noteId} className="field__label">
            Note
          </label>
          <textarea
            id={noteId}
            className="textarea"
            rows={3}
            maxLength={NOTE_MAX}
            aria-describedby={counterId}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <p id={counterId} className="saved-row__count muted small">
            {note.length}/{NOTE_MAX}
          </p>
          <div className="btn-row saved-row__actions">
            <button
              type="button"
              className="btn btn--primary btn--sm"
              aria-describedby={labelId}
              aria-disabled={busy !== null || undefined}
              onClick={() => void act('note', () => onSaveNote(saved, note))}
            >
              Save note
            </button>
            <Link to={`/clip/${encodeURIComponent(clip.id)}`} className="link-btn" aria-describedby={labelId}>
              Open
              <Icon name="external" size={16} />
            </Link>
            <button
              type="button"
              className="link-btn link-btn--danger"
              aria-describedby={labelId}
              aria-disabled={busy !== null || undefined}
              onClick={() => void act('remove', () => onRemove(saved))}
            >
              <Icon name="trash" size={16} />
              Remove
            </button>
            <span className="row-note" role="status">
              {flash ? 'Note saved' : ''}
            </span>
          </div>
          {error ? (
            <p className="inline-error" role="alert">
              {error}
            </p>
          ) : null}
        </div>
      </article>
    </li>
  );
});
