// Inline 18x18 line icons (no icon library): stroke 1.5, round caps and joins, as in the design reference.
// The shapes are hoisted static JSX, so they are created once.

const PATHS = {
  /** Three lines, 14 wide, at y 4.5, 9 and 13.5. */
  menu: <path d="M2 4.5h14M2 9h14M2 13.5h14" />,
  /** Magnifier: circle r 5.5 at 8,8 and a handle to 16,16. */
  search: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="m12 12 4 4" />
    </>
  ),
  /** Video camera: rounded rect at 1.5,4.5 (11 x 9) and a triangle out to 16.5. */
  camera: (
    <>
      <rect x="1.5" y="4.5" width="11" height="9" rx="2" />
      <path d="M12.5 9 16.5 6v6z" />
    </>
  ),
  /** Hexagon outline. */
  zones: <path d="M9 2l6.1 3.5v7L9 16l-6.1-3.5v-7z" />,
  /** Bookmark outline. */
  bookmark: <path d="M4.5 2.5h9v13L9 12.5l-4.5 3z" />,
  /** A cross, 9 wide. */
  close: <path d="m4.5 4.5 9 9m0-9-9 9" />,
  /** Bin: lid at y 5, handle, body narrowing to y 15, two inner lines. */
  trash: <path d="M3 5h12M7 5V3.5h4V5M4.5 5l.8 10h7.4l.8-10M7.5 8v4.5m3-4.5v4.5" />,
  /** A frame (15 x 11) with a smaller box outlined inside it: an evidence frame. */
  proof: (
    <>
      <rect x="1.5" y="3.5" width="15" height="11" rx="2" />
      <rect x="7" y="7" width="5" height="4" />
    </>
  ),
  /** Calendar: body from y 3.5, a header line at 7.5 and two rings. */
  calendar: (
    <>
      <rect x="2.5" y="3.5" width="13" height="12" rx="2" />
      <path d="M2.5 7.5h13M6 2v3m6-3v3" />
    </>
  ),
  /** A cube drawn as three faces: any physical object. */
  object: <path d="M9 1.8l6.5 3.7v7L9 16.2l-6.5-3.7v-7zM2.5 5.5L9 9.2l6.5-3.7M9 9.2v7" />,
  /** An arrow up out of a tray. */
  upload: <path d="M9 12V3M5.5 6.5L9 3l3.5 3.5M3 12.5V15h12v-2.5" />,
  /** Folder outline with a tab. */
  folder: <path d="M2 4.5h5l1.5 2H16v8H2z" />,
  /** A tick. */
  check: <path d="M3.5 9.5L7 13l7.5-8" />,
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 18 18"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
