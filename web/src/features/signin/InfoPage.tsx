import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { usePageTitle } from '../../hooks/usePageTitle';
import '../../styles/signin.css';
import { SignInMark } from './SignInMark';

const MAIN_ID = 'info-main';

/** A public page (no sign-in needed) of short, plain statements: the layout of /privacy and /security. */
export function InfoPage({ title, intro, points }: { title: string; intro: string; points: readonly string[] }): ReactNode {
  usePageTitle(title);
  return (
    <div className="info">
      <a className="skip-link" href={`#${MAIN_ID}`}>
        Skip to content
      </a>
      <header className="info__bar">
        <Link to="/sign-in" className="info__brand">
          <SignInMark size={28} />
          AskFootage
        </Link>
        <nav aria-label="Public pages" className="info__nav">
          <Link to="/privacy">Privacy</Link>
          <Link to="/security">Security</Link>
        </nav>
      </header>
      <main className="info__main" id={MAIN_ID} tabIndex={-1}>
        <h1>{title}</h1>
        <p className="info__intro">{intro}</p>
        <ul className="info__list">
          {points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
        <p>
          <Link to="/sign-in">Back to sign in</Link>
        </p>
      </main>
    </div>
  );
}
