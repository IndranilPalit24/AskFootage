import { createContext, use, useCallback, useMemo, type ReactNode } from 'react';
import type { DaySummary, Status } from '../api/generated/types';
import { useAsyncData, type LoadError } from '../hooks/useAsyncData';
import { useApiClient } from './ApiContext';

export interface AppData {
  status: Status | null;
  /** The 7 days from GET /api/days, oldest first. */
  days: DaySummary[] | null;
  /** The server's today: the last entry of GET /api/days. Never the browser clock. */
  today: string | null;
  loading: boolean;
  error: LoadError | null;
  reload: () => void;
  /** Fetches the day counts again (after an upload). */
  refreshDays: () => Promise<void>;
}

interface Boot {
  status: Status;
  days: DaySummary[];
}

const AppDataContext = createContext<AppData | null>(null);

const BOOT_KEY = ['boot'];

export function AppDataProvider({ children }: { children: ReactNode }) {
  const client = useApiClient();
  // The days need the camera id from the status, so these two calls run in sequence.
  const boot = useAsyncData<Boot>(async () => {
    const status = await client.getStatus();
    const days = await client.listDays(status.camera.id);
    return { status, days };
  }, BOOT_KEY);

  const cameraId = boot.data?.status.camera.id ?? null;
  const { mutate, reload } = boot;
  const refreshDays = useCallback(async () => {
    if (!cameraId) return;
    const days = await client.listDays(cameraId);
    mutate((current) => ({ ...current, days }));
  }, [client, cameraId, mutate]);

  const value = useMemo<AppData>(() => {
    const days = boot.data?.days ?? null;
    return {
      status: boot.data?.status ?? null,
      days,
      today: days && days.length > 0 ? days[days.length - 1].day : null,
      loading: boot.loading,
      error: boot.error,
      reload,
      refreshDays,
    };
  }, [boot.data, boot.loading, boot.error, reload, refreshDays]);

  return <AppDataContext value={value}>{children}</AppDataContext>;
}

export function useAppData(): AppData {
  const value = use(AppDataContext);
  if (!value) throw new Error('useAppData must be used inside AppDataProvider');
  return value;
}
