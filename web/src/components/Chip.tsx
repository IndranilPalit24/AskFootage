import type { ReactNode } from 'react';

export type ChipTone = 'neutral' | 'accent';

/** A small pill: neutral (grey outline) or accent (tint, as evidence). */
export function Chip({ tone = 'neutral', children }: { tone?: ChipTone; children: ReactNode }) {
  return <span className={tone === 'accent' ? 'chip chip--accent' : 'chip'}>{children}</span>;
}
