import { CLOSING_TEXT, CLOSING_TITLE } from './content';
import { DemoLink } from './DemoLink';

/** The closing navy band. */
export function Closing() {
  return (
    <section className="welcome-band welcome-closing" aria-labelledby="closing-title">
      <div className="welcome-wrap">
        <div className="welcome-closing__column">
          <h2 id="closing-title">{CLOSING_TITLE}</h2>
          <p>{CLOSING_TEXT}</p>
          <div className="btn-row">
            <DemoLink onNavy />
          </div>
        </div>
      </div>
    </section>
  );
}
