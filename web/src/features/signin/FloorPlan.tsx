/**
 * An abstract factory floor plan: walls, bays, aisles and doorways in thin lines. Decoration only: it shows no
 * footage, no people, no camera names and no real place, so it is hidden from assistive technology.
 */
export function FloorPlan() {
  return (
    <svg className="signin__plan" viewBox="0 0 400 260" fill="none" aria-hidden="true" focusable="false">
      {/* Outer wall, with a doorway gap at the bottom left and one on the right. */}
      <path d="M20 20H380V110M380 150V240H120M80 240H20V20" stroke="var(--color-text)" strokeWidth="2" strokeLinecap="round" />
      {/* Inner wall between the bays and the dock, with a doorway. */}
      <path d="M250 20V90M250 120V240" stroke="var(--color-text)" strokeWidth="1.5" strokeLinecap="round" />
      {/* Storage bays. */}
      <g stroke="var(--color-accent)" strokeOpacity="0.6" strokeWidth="1.5">
        <rect x="44" y="44" width="40" height="64" />
        <rect x="96" y="44" width="40" height="64" />
        <rect x="148" y="44" width="40" height="64" />
        <rect x="44" y="150" width="40" height="64" />
        <rect x="96" y="150" width="40" height="64" />
        <rect x="148" y="150" width="40" height="64" />
      </g>
      {/* Aisles. */}
      <g stroke="var(--color-text-muted)" strokeWidth="1" strokeDasharray="4 5" strokeLinecap="round">
        <path d="M34 128H240" />
        <path d="M212 34V226" />
      </g>
      {/* Loading bays on the right. */}
      <g stroke="var(--color-text)" strokeWidth="1.5">
        <rect x="280" y="40" width="70" height="36" />
        <rect x="280" y="170" width="70" height="36" />
      </g>
    </svg>
  );
}
