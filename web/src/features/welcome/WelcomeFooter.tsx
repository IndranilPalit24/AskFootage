import { SECTION_LINKS } from './content';

export function WelcomeFooter() {
  return (
    <footer className="welcome-footer">
      <div className="welcome-wrap welcome-footer__inner">
        <p>AskFootage. Ask your footage. Get the clip and the proof.</p>
        <nav aria-label="Footer">
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
      </div>
    </footer>
  );
}
