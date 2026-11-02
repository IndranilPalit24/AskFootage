import type { AuthMode } from './authMode';

/** Copy shared by both modes. */
export const SIGN_IN_COPY = {
  wordmark: 'AskFootage',
  headlineLines: ['Find the moment.', 'Review the evidence.'],
  tagline: 'Secure access to recorded footage for your operations team.',
  title: 'Sign in to AskFootage',
  lead: 'Use your organization account to continue.',
  microsoftButton: 'Continue with Microsoft',
  ssoButton: 'Continue with company SSO',
  divider: 'or',
  codeLabel: 'Demo access code',
  codeSubmit: 'Continue',
  codeCancel: 'Cancel',
} as const;

/** Shown in demo mode. The first button is disabled and points at it. */
export const DEMO_NOTE = 'Enter the demo access code you were given. This build has no real sign-in; the code only opens the demo screens.';

/** Calm messages for a code that did not work. */
export const CODE_MESSAGES = {
  incomplete: 'Enter all 6 digits.',
  invalid: 'That code is not valid.',
  tooMany: 'Too many attempts. Wait a minute, then try again.',
  failed: 'Could not check the code. Try again.',
} as const;

/**
 * The production copy for "sso" mode, kept here exactly. Nothing renders it in a demo build, and nothing is
 * wired to it yet.
 */
export const SSO_COPY = {
  mfa: 'Multi-factor authentication is managed by your organization.',
  accessLead: 'Need access? ',
  accessLink: 'Contact your factory administrator.',
} as const;

/** What each mode shows below the buttons. Only the demo row is ever reached by the running app. */
export function modeCopy(mode: AuthMode) {
  return mode === 'sso' ? { note: null, sso: true, demo: false } : { note: DEMO_NOTE, sso: false, demo: true };
}
