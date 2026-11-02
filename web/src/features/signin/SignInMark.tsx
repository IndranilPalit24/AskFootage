/** The camera mark: a square bracket frame around a solid cobalt dot. Decorative; the wordmark beside it is the name. */
export function SignInMark({ size = 44 }: { size?: number }) {
  return (
    <svg className="signin__mark" width={size} height={size} viewBox="0 0 44 44" aria-hidden="true" focusable="false">
      <path d="M14 6H6v32h8M30 6h8v32h-8" fill="none" stroke="var(--color-text)" strokeWidth="3.5" strokeLinecap="square" />
      <circle cx="22" cy="22" r="9.5" fill="var(--color-accent)" />
    </svg>
  );
}
