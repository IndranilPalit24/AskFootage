import { useState } from 'react';
import { errorMessage } from '../api/errors';
import { useSavedClipActions, useSavedClipId } from '../app/SavedClipsContext';
import { Icon } from './Icon';

interface SaveClipButtonProps {
  clipId: string;
  describedBy?: string;
  /** The small (36px) button, as inside clip cards. */
  small?: boolean;
}

/** Save clip / Saved toggle. Every instance reads the shared saved store, so all of them agree. */
export function SaveClipButton({ clipId, describedBy, small = false }: SaveClipButtonProps) {
  const savedId = useSavedClipId(clipId);
  const { save, unsave } = useSavedClipActions();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (savedId) await unsave(clipId, savedId);
      else await save(clipId);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className={small ? 'btn btn--sm' : 'btn'}
        aria-pressed={savedId !== undefined}
        aria-describedby={describedBy}
        aria-disabled={busy || undefined}
        onClick={toggle}
      >
        <Icon name="bookmark" size={16} />
        {savedId ? 'Saved' : 'Save clip'}
      </button>
      {error ? (
        <span className="inline-error" role="alert">
          {error}
        </span>
      ) : null}
    </>
  );
}
