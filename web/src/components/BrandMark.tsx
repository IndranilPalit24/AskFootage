/** The product mark: a frame with a marked box inside it (the favicon, drawn inline). Decorative. */
export function BrandMark({ size = 24 }: { size?: number }) {
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
