import { Icon } from '../../components/Icon';
import { FEATURES } from './content';
import { Section } from './Section';

export function Features() {
  return (
    <Section id="features" title="Features" lead="What you can do once footage is added.">
      <ul className="welcome-grid welcome-grid--3">
        {FEATURES.map((feature) => (
          <li key={feature.title} className="card card--padded welcome-feature">
            <span className="welcome-icon">
              <Icon name={feature.icon} size={24} />
            </span>
            <h3>{feature.title}</h3>
            <p>{feature.text}</p>
          </li>
        ))}
      </ul>
    </Section>
  );
}
