/**
 * The permanent disclosure: one quiet line on every screen. It takes no props, has no toggle and cannot be
 * hidden by a caller. It says what the data is, and nothing about any real facility or activity.
 */
export const DISCLOSURE = 'This build includes a generated demo dataset.';

export function DemoDisclosure() {
  return <p className="disclosure">{DISCLOSURE}</p>;
}
