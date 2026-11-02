import { Icon } from '../../components/Icon';
import { PRIVACY_POINTS } from './content';
import { Section } from './Section';

export function Privacy() {
  return (
    <Section id="privacy" title="No face recognition. No identity features." tinted>
      <ul className="welcome-checks">
        {PRIVACY_POINTS.map((point) => (
          <li key={point}>
            <Icon name="check" />
            <span>{point}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}
