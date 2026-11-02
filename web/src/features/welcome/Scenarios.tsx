import { SCENARIOS, SCENARIOS_NOTE } from './content';
import { Section } from './Section';

export function Scenarios() {
  return (
    <Section id="scenarios" title="Example scenarios" lead="The kinds of question people ask of fixed-camera footage.">
      <ul className="welcome-grid welcome-grid--3">
        {SCENARIOS.map((scenario) => (
          <li key={scenario.title} className="card card--padded welcome-scenario">
            <h3>{scenario.title}</h3>
            <p className="welcome-scenario__label">You ask</p>
            <p>{scenario.question}</p>
            <p className="welcome-scenario__label">You get</p>
            <p>{scenario.result}</p>
          </li>
        ))}
      </ul>
      <p className="welcome-note">{SCENARIOS_NOTE}</p>
    </Section>
  );
}
