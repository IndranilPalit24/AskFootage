import { Icon } from '../../components/Icon';
import { PIPELINE, SAMPLE_LABEL } from './content';
import { Section } from './Section';

/** Hoisted: static mock content never changes between renders. */
const MOCKS = [
  <ul key="add" className="mock mock--list">
    <li>
      <span>dock-door-0830.mp4</span>
      <span className="status">
        <span className="cam-dot cam-dot--online" aria-hidden="true" />
        Ready
      </span>
    </li>
    <li>
      <span>dock-door-0900.mp4</span>
      <span className="status">
        <span className="cam-dot cam-dot--online" aria-hidden="true" />
        Ready
      </span>
    </li>
    <li>
      <span>Add recording</span>
      <Icon name="upload" />
    </li>
  </ul>,
  <div key="index" className="mock">
    <p>Objects: person, cardboard box</p>
    <div className="mock__bar" aria-hidden="true">
      <span className="mock__bar-fill" />
    </div>
    <p>Indexed once, saved for every later question.</p>
  </div>,
  <div key="ask" className="mock">
    <p className="mock__ask">
      <Icon name="search" />
      <span>someone carrying a box</span>
    </p>
    <ul className="mock mock--list">
      <li>
        <span>Clip 1</span>
        <span>0:01-0:05</span>
      </li>
      <li>
        <span>Clip 2</span>
        <span>0:42-0:47</span>
      </li>
    </ul>
  </div>,
] as const;

/** Add footage, index once, ask anything: a compact mock for each step. */
export function Pipeline() {
  return (
    <Section id="how" title="How it works" lead="Three steps, and the first two happen once." tinted>
      <ol className="welcome-grid welcome-grid--3">
        {PIPELINE.map((step, index) => (
          <li key={step.title} className="card card--padded welcome-step">
            <p className="welcome-step__number">Step {index + 1}</p>
            <h3>{step.title}</h3>
            <p>{step.text}</p>
            {MOCKS[index]}
            <p className="welcome-sample">{SAMPLE_LABEL}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}
