import { Link } from 'react-router-dom';
import { Icon } from '../../components/Icon';
import { EXAMPLE_QUESTIONS } from '../search/AskBox';
import { DemoLink } from './DemoLink';
import { DEMO_PATH, HEADLINE, HERO_QUESTION } from './content';

/**
 * The navy hero: headline, one line of subtext, the ask box and the demo's own example questions.
 * Find Footage does not read a question from its address, so the ask box is a link into the demo (it
 * says so) rather than a field that would lose what was typed.
 */
export function Hero() {
  return (
    <section className="welcome-band welcome-hero" aria-labelledby="welcome-title">
      <div className="welcome-wrap">
        <div className="welcome-hero__column">
          <h1 id="welcome-title" className="welcome-hero__title">
            {HEADLINE}
          </h1>
          <p className="welcome-hero__sub">
            Type a question in plain English. Get the matching clips, each with the evidence for why it matched.
          </p>
          <Link
            to={DEMO_PATH}
            className="welcome-ask"
            aria-label={`Ask in the demo: ${HERO_QUESTION}`}
            aria-describedby="welcome-ask-note"
          >
            <span className="welcome-ask__question">
              <Icon name="search" />
              <span>{HERO_QUESTION}</span>
            </span>
            <span className="btn btn--primary welcome-ask__action" aria-hidden="true">
              Ask in the demo
            </span>
          </Link>
          <p id="welcome-ask-note" className="welcome-hero__note">
            Opens the demo, where you type your own question.
          </p>
          <div className="welcome-hero__examples">
            <p className="welcome-hero__note" id="welcome-examples-label">
              Questions the demo suggests:
            </p>
            <ul className="chip-list" aria-labelledby="welcome-examples-label">
              {EXAMPLE_QUESTIONS.map((question) => (
                <li key={question}>
                  <span className="chip welcome-hero__chip">{question}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="btn-row welcome-hero__actions">
            <DemoLink onNavy />
            <a href="#how" className="welcome-band__link">
              See how it works
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
