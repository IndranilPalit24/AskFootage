// AskFootage has no authentication. This constant says which sign-in page copy is shown; it is not a session,
// a guard or a setting anyone can change at runtime.
//
//   "demo"  the only mode implemented: single sign-on is not configured, so the page offers "Continue to demo".
//   "sso"   production copy only (see ssoCopy.ts). Nothing is wired to it: no redirect, no session.
//
// It is a compile-time constant on purpose: not read from the URL, storage or the environment, so no one can
// switch a demo build into showing a sign-in that does not exist. Changing it is a code change with a review.

export const AUTH_MODES = ['demo', 'sso'] as const;
export type AuthMode = (typeof AUTH_MODES)[number];

export const AUTH_MODE: AuthMode = 'demo';
