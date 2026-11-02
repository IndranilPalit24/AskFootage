import { DemoLink } from './DemoLink';
import { SECTION_LINKS } from './content';

/** Wordmark, in-page links to the sections, and "Try the demo". Sticky from tablet width up. */
export function WelcomeTopbar() {
  return (
    <header className="welcome-topbar">
      <div className="welcome-wrap welcome-topbar__inner">
        <a href="#top" className="welcome-topbar__brand">
          AskFootage
        </a>
        <nav className="welcome-topbar__nav" aria-label="Page sections">
          <ul className="welcome-topbar__links">
            {SECTION_LINKS.map((link) => (
              <li key={link.id}>
                <a href={`#${link.id}`} className="welcome-topbar__link">
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <DemoLink />
      </div>
    </header>
  );
}
