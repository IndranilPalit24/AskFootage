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
  access: 'Need access? Contact your factory administrator.',
  demoButton: 'Continue to demo',
} as const;

/** Shown in demo mode, and the description of both disabled buttons. */
export const DEMO_NOTE = 'Single sign-on is not configured in this build.';

/**
 * The production copy for "sso" mode, kept here exactly. Nothing renders it in a demo build, and nothing is
 * wired to it yet.
 */
export const SSO_COPY = {
  mfa: 'Multi-factor authentication is managed by your organization.',
} as const;

/** What each mode shows below the buttons. Only the demo row is ever reached by the running app. */
export function modeCopy(mode: AuthMode) {
  return mode === 'sso' ? { note: null, mfa: SSO_COPY.mfa, demo: false } : { note: DEMO_NOTE, mfa: null, demo: true };
}
