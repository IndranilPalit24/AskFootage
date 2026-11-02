import { Icon } from '../../components/Icon';
import { INTEGRATIONS } from './content';
import { Section } from './Section';

/** Neutral tiles for the kinds of source it reads. Generic names only. */
export function Integrations() {
  return (
    <Section id="sources" title="Works with the footage you already have" tinted>
      <ul className="welcome-grid welcome-grid--3">
        {INTEGRATIONS.map((item) => (
          <li key={item.title} className="card card--padded welcome-feature">
            <span className="welcome-icon">
              <Icon name={item.icon} size={24} />
            </span>
            <h3>{item.title}</h3>
            <p>{item.text}</p>
          </li>
        ))}
      </ul>
    </Section>
  );
}
