import { createContext, use, useEffect, useMemo, useSyncExternalStore, type ReactNode } from 'react';
import type { ApiClient } from '../api/client';
import { ApiError } from '../api/errors';
import type { SavedClip } from '../api/generated/types';
import { useApiClient } from './ApiContext';

/**
 * Which clips are saved: clipId -> savedClipId. A tiny external store, so each Save clip button subscribes
 * to its own clip's entry and re-renders only when that entry changes, not when any other clip is saved.
 */
class SavedIdsStore {
  private ids: ReadonlyMap<string, string> = new Map();
  private readonly listeners = new Set<() => void>();

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  get(clipId: string): string | undefined {
    return this.ids.get(clipId);
  }

  update(change: (ids: Map<string, string>) => void): void {
    const next = new Map(this.ids);
    change(next);
    this.ids = next;
    for (const listener of this.listeners) listener();
  }

  replace(list: SavedClip[]): void {
    this.update((ids) => {
      ids.clear();
      for (const saved of list) ids.set(saved.clip.id, saved.id);
    });
  }
}

export interface SavedClipActions {
  /** Saves a clip with an empty note. */
  save: (clipId: string) => Promise<void>;
  /** Removes a saved clip. A clip that is already gone counts as removed. */
  unsave: (clipId: string, savedId: string) => Promise<void>;
}

interface SavedClipsValue extends SavedClipActions {
  store: SavedIdsStore;
}

// The value never changes for a given client, so this context itself never re-renders anyone.
const SavedClipsContext = createContext<SavedClipsValue | null>(null);

function createValue(client: ApiClient): SavedClipsValue {
  const store = new SavedIdsStore();
  return {
    store,
    async save(clipId) {
      try {
        const saved = await client.saveClip({ clipId, note: '' });
        store.update((ids) => ids.set(clipId, saved.id));
      } catch (error) {
        if (error instanceof ApiError && error.code === 'already_saved') {
          // Saved elsewhere meanwhile: take the server's list as the truth.
          store.replace(await client.listSavedClips());
          return;
        }
        throw error;
      }
    },
    async unsave(clipId, savedId) {
      try {
        await client.deleteSavedClip(savedId);
      } catch (error) {
        if (!(error instanceof ApiError && error.code === 'not_found')) throw error;
      }
      store.update((ids) => ids.delete(clipId));
    },
  };
}

export function SavedClipsProvider({ children }: { children: ReactNode }) {
  const client = useApiClient();
  const value = useMemo(() => createValue(client), [client]);
  useEffect(() => {
    let active = true;
    client.listSavedClips().then(
      (list) => {
        if (active) value.store.replace(list);
      },
      () => {
        // Leave the store empty; each Save clip button reports its own errors.
      },
    );
    return () => {
      active = false;
    };
  }, [client, value]);

  return <SavedClipsContext value={value}>{children}</SavedClipsContext>;
}

function useSavedClipsValue(): SavedClipsValue {
  const value = use(SavedClipsContext);
  if (!value) throw new Error('Saved clip hooks must be used inside SavedClipsProvider');
  return value;
}

/** The saved-clip id of one clip, or undefined when it is not saved. Re-renders only when that changes. */
export function useSavedClipId(clipId: string): string | undefined {
  const { store } = useSavedClipsValue();
  return useSyncExternalStore(store.subscribe, () => store.get(clipId));
}

export function useSavedClipActions(): SavedClipActions {
  return useSavedClipsValue();
}
