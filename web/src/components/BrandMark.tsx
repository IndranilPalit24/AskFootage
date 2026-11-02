/**
 * The product mark: a frame (square brackets) around a marked box, the favicon drawn inline. Decorative.
 * plain: just the brackets and a solid cobalt dot, no tile (the sidebar's wordmark).
 */
export function BrandMark({ size = 24, plain = false }: { size?: number; plain?: boolean }) {
  if (plain) {
    return (
      <svg className="topbar__mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path
          d="M8 13V9a1 1 0 0 1 1-1h4M19 8h4a1 1 0 0 1 1 1v4M24 19v4a1 1 0 0 1-1 1h-4M13 24H9a1 1 0 0 1-1-1v-4"
          fill="none"
          stroke="var(--color-text)"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
        <circle cx="16" cy="16" r="4" fill="var(--color-accent)" />
      </svg>
    );
  }
  return (
    <svg className="topbar__mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="6" fill="var(--color-navy)" />
      <path
        d="M8 13V9a1 1 0 0 1 1-1h4M19 8h4a1 1 0 0 1 1 1v4M24 19v4a1 1 0 0 1-1 1h-4M13 24H9a1 1 0 0 1-1-1v-4"
        fill="none"
        stroke="var(--color-on-navy)"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <rect x="12" y="12" width="8" height="8" rx="1" fill="var(--color-player-accent)" />
    </svg>
  );
}
