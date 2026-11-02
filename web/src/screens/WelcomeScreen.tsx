import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { Closing } from '../features/welcome/Closing';
import { Cost } from '../features/welcome/Cost';
import { Features } from '../features/welcome/Features';
import { Hero } from '../features/welcome/Hero';
import { Integrations } from '../features/welcome/Integrations';
import { Pipeline } from '../features/welcome/Pipeline';
import { Privacy } from '../features/welcome/Privacy';
import { ProofPreview } from '../features/welcome/ProofPreview';
import { Scenarios } from '../features/welcome/Scenarios';
import { WelcomeFooter } from '../features/welcome/WelcomeFooter';
import { WelcomeTopbar } from '../features/welcome/WelcomeTopbar';

const MAIN_ID = 'welcome-main';

/**
 * The welcome page at /welcome: what AskFootage does, with sample previews, and links into the demo.
 * It sits outside the app shell (no drawer, no day chip): it is a page about the app, not a screen of it.
 */
export function WelcomeScreen() {
  // Arriving by an in-app link with a #section (the sign-in page's Privacy link): the browser does not scroll
  // after a client-side navigation, so scroll to the section once the page is there.
  const { hash } = useLocation();
  useEffect(() => {
    if (hash.length > 1) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView?.();
  }, [hash]);
  return (
    <div className="welcome" id="top">
      <a className="skip-link" href={`#${MAIN_ID}`}>
        Skip to content
      </a>
      <WelcomeTopbar />
      <main className="welcome-main" id={MAIN_ID} tabIndex={-1}>
        <Hero />
        <Pipeline />
        <ProofPreview />
        <Features />
        <Integrations />
        <Scenarios />
        <Privacy />
        <Cost />
        <Closing />
      </main>
      <WelcomeFooter />
    </div>
  );
}
