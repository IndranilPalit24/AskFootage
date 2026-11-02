import { useCallback, useRef, useState } from 'react';
import type { SavedClip } from '../api/generated/types';
import { useApiClient } from '../app/ApiContext';
import { useAppData } from '../app/AppDataContext';
import { useSavedClipActions } from '../app/SavedClipsContext';
import { Link } from 'react-router-dom';
import { EmptyState } from '../components/EmptyState';
import { ClipListSkeleton } from '../components/Skeletons';
import { usePageTitle } from '../hooks/usePageTitle';
import { SavedClipRow } from '../features/saved/SavedClipRow';
import { useAsyncData } from '../hooks/useAsyncData';
import { formatShortDay } from '../lib/dates';

const ALL_DAYS = '';

const loading = <ClipListSkeleton label="Loading saved clips…" />;

export function SavedClipsScreen() {
  usePageTitle('Saved clips');
  const client = useApiClient();
  const { days } = useAppData();
  const { unsave } = useSavedClipActions();
  // Its own filter, starting at "All days": the shared selected day is about footage, not the saved list.
  const [dayFilter, setDayFilter] = useState(ALL_DAYS);
  const saved = useAsyncData(() => client.listSavedClips(dayFilter || undefined), ['saved-clips', dayFilter]);
  const [announcement, setAnnouncement] = useState('');
  const headingRef = useRef<HTMLHeadingElement>(null);

  const { mutate } = saved;

  const saveNote = useCallback(
    async (item: SavedClip, note: string) => {
      const updated = await client.updateSavedClip(item.id, { note });
      mutate((current) => current.map((entry) => (entry.id === updated.id ? updated : entry)));
    },
    [client, mutate],
  );

  const remove = useCallback(
    async (item: SavedClip) => {
      // Through the shared actions, so every Save clip button learns the clip is no longer saved.
      await unsave(item.clip.id, item.id);
      mutate((current) => current.filter((entry) => entry.id !== item.id));
      setAnnouncement(`Removed ${item.clip.label}.`);
      // The row (and the focused button) is gone: keep keyboard focus on the page.
      headingRef.current?.focus();
    },
    [unsave, mutate],
  );

  let body;
  if (saved.error && !saved.data) {
    body = (
      <EmptyState
        tone="error"
        title="Saved clips could not be loaded"
        action={
          <button type="button" className="btn" onClick={saved.reload}>
            Try again
          </button>
        }
      >
        <span className="error-text">{saved.error.message}</span>
      </EmptyState>
    );
  } else if (!saved.data) {
    body = loading;
  } else if (saved.data.length === 0) {
    body = (
      <EmptyState
        title={dayFilter ? 'Nothing saved for this day' : 'Your saved clips appear here'}
        action={
          <Link to="/" className="btn btn--primary">
            Find footage
          </Link>
        }
      >
        {dayFilter
          ? `No saved clips from ${formatShortDay(dayFilter)}.`
          : 'No saved clips yet. Use Save clip on any result to keep it here.'}
      </EmptyState>
    );
  } else {
    body = (
      <ul className="clip-list" aria-label="Saved clips">
        {saved.data.map((item) => (
          <SavedClipRow key={item.id} saved={item} onSaveNote={saveNote} onRemove={remove} />
        ))}
      </ul>
    );
  }

  return (
    <div className="screen--wide">
      <div className="page-head">
        <div>
          <h1 ref={headingRef} tabIndex={-1}>
            Saved clips
          </h1>
          <p className="page-head__subtitle">Clips you kept as evidence, with your notes.</p>
        </div>
        <div className="field field--inline">
          <label htmlFor="saved-day" className="field__label">
            Day
          </label>
          <select
            id="saved-day"
            className="select"
            value={dayFilter}
            onChange={(event) => setDayFilter(event.target.value)}
          >
            <option value={ALL_DAYS}>All days</option>
            {(days ?? []).map((entry) => (
              <option key={entry.day} value={entry.day}>
                {formatShortDay(entry.day)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="visually-hidden" role="status">
        {announcement}
      </p>
      {body}
    </div>
  );
}
