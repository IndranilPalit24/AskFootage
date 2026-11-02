import { InfoPage } from '../features/signin/InfoPage';

// Only what the app does today (README and code). No compliance claims, certifications or policies.
export const PRIVACY_POINTS: readonly string[] = [
  'Recorded footage stays on the machine that runs AskFootage. The app has no upload or sharing feature.',
  'AskFootage finds objects and movements, such as a person carrying a box. It has no face recognition and no identity features, and never works out who someone is.',
  'A camera password is checked when you add a camera and is never stored.',
  'Where Meta AI is used: when live indexing is switched on, a prepared copy of the footage is sent to a hosted Meta AI video-analysis service to find objects. Questions are read on this machine. The demo build replays saved answers and sends nothing.',
  'The demo build has no accounts and no authentication, and it shows a generated demo dataset. A demo access code you were given opens the demo screens; it is not tied to a person.',
];

export function PrivacyScreen() {
  return <InfoPage title="Privacy" intro="What AskFootage does with your footage, and what it does not do." points={PRIVACY_POINTS} />;
}
