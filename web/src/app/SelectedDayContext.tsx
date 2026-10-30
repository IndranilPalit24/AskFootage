import { createContext, use, useMemo, useState, type ReactNode } from 'react';
import { useAppData } from './AppDataContext';

export interface SelectedDay {
  /** The day every screen works on; today (the server's) until someone picks another. Null while loading. */
  day: string | null;
  setDay: (day: string) => void;
}

const SelectedDayContext = createContext<SelectedDay | null>(null);

export function SelectedDayProvider({ children }: { children: ReactNode }) {
  const { today } = useAppData();
  const [chosen, setChosen] = useState<string | null>(null);
  // Derived, not synced by an effect: no pick yet means "today".
  const day = chosen ?? today;
  const value = useMemo<SelectedDay>(() => ({ day, setDay: setChosen }), [day]);
  return <SelectedDayContext value={value}>{children}</SelectedDayContext>;
}

export function useSelectedDay(): SelectedDay {
  const value = use(SelectedDayContext);
  if (!value) throw new Error('useSelectedDay must be used inside SelectedDayProvider');
  return value;
}
