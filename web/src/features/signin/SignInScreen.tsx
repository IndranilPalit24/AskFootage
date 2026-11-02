import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { useApiClient } from '../../app/ApiContext';
import packageJson from '../../../package.json';
import { DemoDisclosure } from '../../components/DemoDisclosure';
import { Icon } from '../../components/Icon';
import { usePageTitle } from '../../hooks/usePageTitle';
import '../../styles/signin.css';
import { CodeEntry } from './CodeEntry';
import { AUTH_MODE, type AuthMode } from './authMode';
import { modeCopy, SIGN_IN_COPY, SSO_COPY } from './copy';
import { startDemoSession, useDemoSession } from './demoSession';
import { FloorPlan } from './FloorPlan';
import { SignInMark } from './SignInMark';

const NOTE_ID = 'signin-note';
const MAIN_ID = 'signin-main';

/**
 * A disabled sign-in method. aria-disabled (not disabled) keeps it in the tab order, so a keyboard or screen
 * reader user finds it and hears why it does nothing: the note it points to. Clicks are ignored.
 */
function UnavailableButton({ icon, label, variant }: { icon: 'shield' | 'building'; label: string; variant: 'cobalt' | 'plain' }) {
  return (
    <button
      type="button"
      className={`signin__btn signin__btn--${variant}`}
      aria-disabled="true"
      aria-describedby={NOTE_ID}
      onClick={(event) => event.preventDefault()}
    >
      <Icon name={icon} size={26} />
      {label}
    </button>
  );
}

/**
 * The sign-in page content for a mode. Exported for tests only: the running app always passes AUTH_MODE, a
 * compile-time constant, so "sso" cannot be reached by a URL, storage or environment value.
 */
export function SignInContent({
  mode,
  checkCode,
  onAccepted,
}: {
  mode: AuthMode;
  checkCode?: (code: string) => Promise<unknown>;
  onAccepted?: () => void;
}) {
  usePageTitle('Sign in');
  const copy = modeCopy(mode);
  const [entering, setEntering] = useState(false);
  const ssoButton = useRef<HTMLButtonElement>(null);
  const wasEntering = useRef(false);
  // Back from the code entry: focus returns to the button that opened it.
  useEffect(() => {
    if (wasEntering.current && !entering) ssoButton.current?.focus();
    wasEntering.current = entering;
  }, [entering]);
  return (
    <div className="signin">
      <a className="skip-link" href={`#${MAIN_ID}`}>
        Skip to content
      </a>
      <aside className="signin__brand" aria-label="About AskFootage">
        <p className="signin__wordmark">
          <SignInMark />
          {SIGN_IN_COPY.wordmark}
        </p>
        <FloorPlan />
        <div className="signin__pitch">
          <p className="signin__headline">
            {SIGN_IN_COPY.headlineLines.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </p>
          <p className="signin__tagline">{SIGN_IN_COPY.tagline}</p>
        </div>
      </aside>
      <div className="signin__side">
        <main className="signin__main" id={MAIN_ID} tabIndex={-1}>
          <div className="signin__form">
            <h1>{SIGN_IN_COPY.title}</h1>
            <p className="signin__lead">{SIGN_IN_COPY.lead}</p>
            <UnavailableButton icon="shield" label={SIGN_IN_COPY.microsoftButton} variant="cobalt" />
            <p className="signin__divider">
              <span>{SIGN_IN_COPY.divider}</span>
            </p>
            {copy.demo && checkCode && onAccepted ? (
              entering ? (
                <CodeEntry check={checkCode} onAccepted={onAccepted} onCancel={() => setEntering(false)} />
              ) : (
                <button ref={ssoButton} type="button" className="signin__btn" onClick={() => setEntering(true)}>
                  <Icon name="building" size={26} />
                  {SIGN_IN_COPY.ssoButton}
                </button>
              )
            ) : (
              <UnavailableButton icon="building" label={SIGN_IN_COPY.ssoButton} variant="plain" />
            )}
            {copy.note ? (
              <p className="signin__note" id={NOTE_ID}>
                {copy.note}
              </p>
            ) : null}
            {copy.sso ? (
              <>
                <p className="signin__note">{SSO_COPY.mfa}</p>
                <p className="signin__access">
                  {SSO_COPY.accessLead}
                  <span className="signin__link">{SSO_COPY.accessLink}</span>
                </p>
              </>
            ) : null}
          </div>
        </main>
        <footer className="signin__footer">
          <Link to="/privacy">Privacy</Link>
          <span aria-hidden="true">|</span>
          <Link to="/security">Security</Link>
          <span aria-hidden="true">|</span>
          <span>v{packageJson.version}</span>
        </footer>
        <div className="signin__disclosure">
          <DemoDisclosure />
        </div>
      </div>
    </div>
  );
}

/** Where to go after the demo starts: the path the guard sent the visitor away from, if it is a plain app path. */
function returnPath(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  if (typeof from !== 'string' || !from.startsWith('/') || from.startsWith('//') || from.startsWith('/sign-in')) return '/';
  return from;
}

/**
 * /sign-in. There is no real authentication in AskFootage: the SSO button asks for a demo access code, the API checks it,
 * and success sets a UI-only flag (see demoSession.ts). With the flag set, this page sends the visitor on to Find Footage,
 * or back to the page they asked for.
 */
export function SignInScreen() {
  const client = useApiClient();
  const entered = useDemoSession();
  const { state } = useLocation();
  if (entered) return <Navigate to={returnPath(state)} replace />;
  return <SignInContent mode={AUTH_MODE} checkCode={(code) => client.checkDemoCode(code)} onAccepted={startDemoSession} />;
}
