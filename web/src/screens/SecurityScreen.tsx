import { InfoPage } from '../features/signin/InfoPage';

// Only what is true of this build. It makes no claim that anything is protected.
export const SECURITY_POINTS: readonly string[] = [
  'The demo build has no accounts and no authentication. Nothing in it is protected by a sign-in.',
  'A demo access code opens the demo screens. It is a gate for the demo build, not a security control: the code is checked by the server, but only that one check uses it, and the rest of the API is not authenticated. Entering a valid code sets a flag in this browser tab.',
  'Do not expose this build to a network you do not trust.',
  'Camera passwords are checked when a camera is added and are never stored. Camera lists never show passwords, addresses or stream links.',
  'The interface carries no API keys. Single sign-on is not available in this build.',
];

export function SecurityScreen() {
  return <InfoPage title="Security" intro="What this build does and does not do to protect access." points={SECURITY_POINTS} />;
}
