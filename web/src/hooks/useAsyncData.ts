import { useCallback, useEffect, useEffectEvent, useState } from 'react';
import { ApiError, errorMessage } from '../api/errors';

export interface LoadError {
  message: string;
  /** The contract's error code, when the API sent one. */
  code: string | null;
}

interface Slot<T> {
  key: string;
  data: T | undefined;
  error: LoadError | null;
  loading: boolean;
}

export interface AsyncData<T> {
  data: T | undefined;
  error: LoadError | null;
  loading: boolean;
  /** Loads again, keeping the current data on screen until the new answer arrives. */
  reload: () => void;
  /** Changes the loaded data in place (after a write the server confirmed). */
  mutate: (update: (current: T) => T) => void;
}

function toLoadError(error: unknown): LoadError {
  return { message: errorMessage(error), code: error instanceof ApiError ? error.code : null };
}

/**
 * Loads data for a key made of primitives. When the key changes the old data is dropped (it belongs to
 * another day or id); reload() keeps it while refreshing. Pass load = null while a prerequisite is missing.
 */
export function useAsyncData<T>(
  load: (() => Promise<T>) | null,
  keyParts: ReadonlyArray<string | number | boolean | null | undefined>,
): AsyncData<T> {
  const key = keyParts.map((part) => String(part)).join('\u0000');
  const enabled = load !== null;
  const [slot, setSlot] = useState<Slot<T>>({ key, data: undefined, error: null, loading: true });
  const [version, setVersion] = useState(0);

  const runLoad = useEffectEvent(() => (load ? load() : Promise.reject(new Error('Nothing to load'))));

  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    setSlot((prev) =>
      prev.key === key
        ? { ...prev, loading: true, error: null }
        : { key, data: undefined, error: null, loading: true },
    );
    runLoad().then(
      (data) => {
        if (active) setSlot({ key, data, error: null, loading: false });
      },
      (error: unknown) => {
        if (active) setSlot((prev) => ({ key, data: prev.key === key ? prev.data : undefined, error: toLoadError(error), loading: false }));
      },
    );
    return () => {
      active = false;
    };
  }, [key, version, enabled]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const mutate = useCallback(
    (update: (current: T) => T) =>
      setSlot((prev) => (prev.data === undefined ? prev : { ...prev, data: update(prev.data) })),
    [],
  );

  // Derived during render: data that belongs to another key is never shown.
  const current = slot.key === key && enabled ? slot : null;
  return {
    data: current?.data,
    error: current?.error ?? null,
    loading: current ? current.loading : true,
    reload,
    mutate,
  };
}
