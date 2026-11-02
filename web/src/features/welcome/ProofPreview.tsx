import { PROOF_SAMPLE, SAMPLE_LABEL } from './content';
import { Section } from './Section';

const { clipSeconds, matchStart, matchEnd } = PROOF_SAMPLE;
const INTERVAL_STYLE = {
  left: `${(matchStart / clipSeconds) * 100}%`,
  width: `${((matchEnd - matchStart) / clipSeconds) * 100}%`,
} as const;

/**
 * A drawing of the clip detail screen, not a screenshot and not real footage: a frame placeholder with a
 * red box around a carried box, the matched interval on the timeline, and the "Why this matched" facts.
 * The shapes are plain rectangles; no one is depicted and nothing identifies anyone.
 */
export function ProofPreview() {
  return (
    <Section
      id="proof"
      title="Every clip comes with its proof"
      lead="Open a result to see the frame, the time range and the reason it matched. Check the match yourself."
    >
      <div className="welcome-proof">
        <figure className="welcome-proof__clip">
          <svg
            className="welcome-proof__frame"
            viewBox="0 0 320 180"
            role="img"
            aria-label="Sample frame: a placeholder picture of a person carrying a box, with a red box drawn around the box"
          >
            <rect className="proof-svg__bg" width="320" height="180" />
            <rect className="proof-svg__floor" y="132" width="320" height="48" />
            <rect className="proof-svg__shape" x="130" y="44" width="40" height="92" />
            <rect className="proof-svg__shape" x="166" y="88" width="44" height="40" />
            <rect className="proof-svg__box" x="160" y="82" width="56" height="52" />
            <rect className="proof-svg__tag" x="160" y="62" width="92" height="20" />
            <text className="proof-svg__tag-text" x="166" y="76">
              cardboard box
            </text>
          </svg>
          <div className="welcome-proof__timeline">
            <div className="welcome-proof__track" aria-hidden="true">
              <span className="welcome-proof__interval" style={INTERVAL_STYLE} />
            </div>
            <p className="welcome-proof__ticks" aria-hidden="true">
              <span>0:00</span>
              <span>0:10</span>
            </p>
            <figcaption className="welcome-proof__caption">
              Matched interval {PROOF_SAMPLE.timeRange}. {SAMPLE_LABEL}, not real footage.
            </figcaption>
          </div>
        </figure>
        <div className="card card--padded welcome-why">
          <h3>Why this matched</h3>
          <dl className="welcome-facts">
            <div>
              <dt>Relation</dt>
              <dd>{PROOF_SAMPLE.relation}</dd>
            </div>
            <div>
              <dt>Time range</dt>
              <dd>{PROOF_SAMPLE.timeRange}</dd>
            </div>
            <div>
              <dt>Object</dt>
              <dd>{PROOF_SAMPLE.object}</dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd>{PROOF_SAMPLE.confidence}</dd>
            </div>
          </dl>
          <p className="welcome-sample">{SAMPLE_LABEL}</p>
        </div>
      </div>
    </Section>
  );
}
