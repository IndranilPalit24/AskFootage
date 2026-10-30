import { memo, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../../api/errors';
import type { SavedClip } from '../../api/generated/types';
import { ClipThumb } from '../../components/ClipThumb';
import { formatShortDay } from '../../lib/dates';

export const NOTE_MAX = 500;
const NOTE_SAVED_FLASH_MS = 2000;

interface SavedClipRowProps {
  saved: SavedClip;
  onSaveNote: (saved: SavedClip, note: string) => Promise<void>;
  onRemove: (saved: SavedClip) => Promise<void>;
}

/** One saved clip: still, label, day and time, an editable note (Save note), Open and Remove. */
export const SavedClipRow = memo(function SavedClipRow({ saved, onSaveNote, onRemove }: SavedClipRowProps) {
  const { clip } = saved;
  const [note, setNote] = useState(saved.note);
  const [busy, setBusy] = useState<'note' | 'remove' | null>(null);
  const [flash, setFlash] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const labelId = `saved-label-${saved.id}`;
  const noteId = `saved-note-${saved.id}`;

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
        <ClipThumb url={clip.thumbnailUrl} />
        <div className="saved-row__body">
          <h2 id={labelId} className="clip-card__label" title={clip.label}>
            {clip.label}
          </h2>
          <p className="clip-card__time">
            {formatShortDay(clip.day)} · {clip.startTime}
          </p>
          <div className="field">
            <label htmlFor={noteId} className="field__label">
              Note
            </label>
            <textarea
              id={noteId}
              className="textarea"
              rows={2}
              maxLength={NOTE_MAX}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
          <div className="btn-row">
            <button
              type="button"
              className="btn btn--sm"
              aria-describedby={labelId}
              aria-disabled={busy !== null || undefined}
              onClick={() => void act('note', () => onSaveNote(saved, note))}
            >
              Save note
            </button>
            <Link to={`/clip/${encodeURIComponent(clip.id)}`} className="btn btn--sm" aria-describedby={labelId}>
              Open
            </Link>
            <button
              type="button"
              className="btn btn--sm"
              aria-describedby={labelId}
              aria-disabled={busy !== null || undefined}
              onClick={() => void act('remove', () => onRemove(saved))}
            >
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
