import { Hero } from '../features/welcome/Hero';
import { WelcomeTopbar } from '../features/welcome/WelcomeTopbar';

const MAIN_ID = 'welcome-main';

/**
 * The welcome page at /welcome: what AskFootage does, with sample previews, and links into the demo.
 * It sits outside the app shell (no drawer, no day chip): it is a page about the app, not a screen of it.
 */
export function WelcomeScreen() {
  return (
    <div className="welcome" id="top">
      <a className="skip-link" href={`#${MAIN_ID}`}>
        Skip to content
      </a>
      <WelcomeTopbar />
      <main className="welcome-main" id={MAIN_ID} tabIndex={-1}>
        <Hero />
      </main>
    </div>
  );
}
