import { createContext, use, useCallback, useMemo, type ReactNode } from 'react';
import type { Camera, DaySummary } from '../api/generated/types';
import { useAsyncData, type LoadError } from '../hooks/useAsyncData';
import { useApiClient } from './ApiContext';

export interface AppData {
  /** The 7 days from GET /api/days (all cameras), oldest first. */
  days: DaySummary[] | null;
  /** The server's today: the last entry of GET /api/days. Never the browser clock. */
  today: string | null;
  /** Every camera, in id order: the last list the server sent (the registry keeps it fresh). */
  cameras: Camera[] | null;
  loading: boolean;
  error: LoadError | null;
  reload: () => void;
  /** Replaces the camera list with what the server confirmed. Return the same array to change nothing. */
  setCameras: (update: (current: Camera[]) => Camera[]) => void;
}

interface Boot {
  days: DaySummary[];
  cameras: Camera[];
}

const AppDataContext = createContext<AppData | null>(null);

const BOOT_KEY = ['boot'];

export function AppDataProvider({ children }: { children: ReactNode }) {
  const client = useApiClient();
  // Independent of each other, so both start at once.
  const boot = useAsyncData<Boot>(async () => {
    const [days, cameras] = await Promise.all([client.listDays(), client.listCameras()]);
    return { days, cameras };
  }, BOOT_KEY);

  const { mutate, reload } = boot;
  const setCameras = useCallback(
    (update: (current: Camera[]) => Camera[]) =>
      mutate((current) => {
        const cameras = update(current.cameras);
        return cameras === current.cameras ? current : { ...current, cameras };
      }),
    [mutate],
  );

  const value = useMemo<AppData>(() => {
    const days = boot.data?.days ?? null;
    return {
      days,
      today: days && days.length > 0 ? days[days.length - 1].day : null,
      cameras: boot.data?.cameras ?? null,
      loading: boot.loading,
      error: boot.error,
      reload,
      setCameras,
    };
  }, [boot.data, boot.loading, boot.error, reload, setCameras]);

  return <AppDataContext value={value}>{children}</AppDataContext>;
}

export function useAppData(): AppData {
  const value = use(AppDataContext);
  if (!value) throw new Error('useAppData must be used inside AppDataProvider');
  return value;
}
