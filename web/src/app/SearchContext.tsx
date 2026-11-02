import { createContext, use, useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import { errorMessage } from '../api/errors';
import type { SearchResponse } from '../api/generated/types';
import { useApiClient } from './ApiContext';

export type SearchState =
  | { phase: 'idle' }
  | { phase: 'loading'; question: string; day: string; camera: string }
  | { phase: 'done'; question: string; day: string; camera: string; response: SearchResponse }
  | { phase: 'error'; question: string; day: string; camera: string; error: string };

export interface SearchActions {
  /** Asks the question about one day (and one camera, or every camera when camera is ''); a newer call wins over an older one still running. */
  run: (question: string, day: string, camera?: string) => void;
}

// The last search lives above the routes, so "Back to results" finds it again.
const SearchStateContext = createContext<SearchState | null>(null);
const SearchActionsContext = createContext<SearchActions | null>(null);

export function SearchProvider({ children }: { children: ReactNode }) {
  const client = useApiClient();
  const [state, setState] = useState<SearchState>({ phase: 'idle' });
  const latest = useRef(0);

  const run = useCallback(
    (question: string, day: string, camera = '') => {
      latest.current += 1;
      const requestId = latest.current;
      setState({ phase: 'loading', question, day, camera });
      // No camera: the search covers every camera.
      client.search(camera === '' ? { question, day } : { question, day, camera }).then(
        (response) => {
          if (latest.current === requestId) setState({ phase: 'done', question, day, camera, response });
        },
        (error: unknown) => {
          if (latest.current === requestId) setState({ phase: 'error', question, day, camera, error: errorMessage(error) });
        },
      );
    },
    [client],
  );

  const actions = useMemo<SearchActions>(() => ({ run }), [run]);

  return (
    <SearchActionsContext value={actions}>
      <SearchStateContext value={state}>{children}</SearchStateContext>
    </SearchActionsContext>
  );
}

export function useSearchState(): SearchState {
  const value = use(SearchStateContext);
  if (!value) throw new Error('useSearchState must be used inside SearchProvider');
  return value;
}

export function useSearchActions(): SearchActions {
  const value = use(SearchActionsContext);
  if (!value) throw new Error('useSearchActions must be used inside SearchProvider');
  return value;
}
