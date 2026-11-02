import { Link } from 'react-router-dom';
import packageJson from '../../../package.json';
import { BrandMark } from '../../components/BrandMark';
import { DemoDisclosure } from '../../components/DemoDisclosure';
import { Icon } from '../../components/Icon';
import { usePageTitle } from '../../hooks/usePageTitle';
import { AUTH_MODE, type AuthMode } from './authMode';
import { modeCopy, SIGN_IN_COPY } from './copy';
import { FloorPlan } from './FloorPlan';

const NOTE_ID = 'signin-note';
const MAIN_ID = 'signin-main';

/**
 * A disabled sign-in method. aria-disabled (not disabled) keeps it in the tab order, so a keyboard or screen
 * reader user finds it and hears why it does nothing: the note it points to.
 */
function UnavailableButton({ icon, label }: { icon: 'shield' | 'building'; label: string }) {
  return (
    <button type="button" className="btn signin__method" aria-disabled="true" aria-describedby={NOTE_ID}>
      <Icon name={icon} />
      {label}
    </button>
  );
}

/**
 * The sign-in page content for a mode. Exported for tests only: the running app always passes AUTH_MODE, a
 * compile-time constant, so "sso" cannot be reached by a URL, storage or environment value.
 */
export function SignInContent({ mode }: { mode: AuthMode }) {
  usePageTitle('Sign in');
  const copy = modeCopy(mode);
  return (
    <div className="signin">
      <a className="skip-link" href={`#${MAIN_ID}`}>
        Skip to content
      </a>
      <aside className="signin__brand" aria-label="About AskFootage">
        <p className="signin__wordmark">
          <BrandMark size={28} />
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
            {copy.demo ? (
              <Link to="/" className="btn btn--primary signin__demo">
                {SIGN_IN_COPY.demoButton}
              </Link>
            ) : null}
            <p className="signin__divider">
              <span>{SIGN_IN_COPY.divider}</span>
            </p>
            <UnavailableButton icon="shield" label={SIGN_IN_COPY.microsoftButton} />
            <UnavailableButton icon="building" label={SIGN_IN_COPY.ssoButton} />
            {copy.note ? (
              <p className="signin__note" id={NOTE_ID}>
                {copy.note}
              </p>
            ) : null}
            {copy.mfa ? <p className="signin__note">{copy.mfa}</p> : null}
            <p className="signin__access">{SIGN_IN_COPY.access}</p>
          </div>
        </main>
        <footer className="signin__footer">
          {/* Privacy is the welcome page's section on what the app does not do; Security has no page, so it is plain text. */}
          <Link to="/welcome#privacy">Privacy</Link>
          <span aria-hidden="true">|</span>
          <span>Security</span>
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

/** /sign-in. There is no authentication in AskFootage: this page never starts a session or guards a route. */
export function SignInScreen() {
  return <SignInContent mode={AUTH_MODE} />;
}
