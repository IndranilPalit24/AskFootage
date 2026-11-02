import {
  CENTS_PER_1000_FRAMES,
  EXAMPLE_MINUTES,
  EXAMPLE_OBJECT_TYPES,
  INDEX_FPS,
  MINIMUM_FRAMES,
  costExample,
  formatCents,
  formatNumber,
} from './content';
import { Section } from './Section';

/** Indexing is the only cost; searching afterwards is free. One worked example, computed from the same constants. */
export function Cost() {
  const example = costExample();
  const minimumSeconds = MINIMUM_FRAMES / INDEX_FPS;
  const minimumCents = (MINIMUM_FRAMES * CENTS_PER_1000_FRAMES) / 1000;
  return (
    <Section
      id="cost"
      title="Cost"
      lead={`About ${formatCents(CENTS_PER_1000_FRAMES)} per 1,000 frames, for each object type, to index. Searching afterwards is free.`}
    >
      <div className="card card--padded welcome-cost">
        <h3>Worked example</h3>
        <p>
          {EXAMPLE_MINUTES} minutes of footage, analysed at {INDEX_FPS} frames per second, with {EXAMPLE_OBJECT_TYPES} object
          types (person, cardboard box, bag, crate).
        </p>
        <dl className="welcome-facts">
          <div>
            <dt>Frames</dt>
            <dd>
              {EXAMPLE_MINUTES} x 60 s x {INDEX_FPS} fps = {formatNumber(example.frames)}
            </dd>
          </div>
          <div>
            <dt>One object type</dt>
            <dd>
              {formatNumber(example.frames)} / 1,000 x {formatCents(CENTS_PER_1000_FRAMES)} = {formatCents(example.centsPerObjectType)}
            </dd>
          </div>
          <div>
            <dt>{EXAMPLE_OBJECT_TYPES} object types</dt>
            <dd>
              {EXAMPLE_OBJECT_TYPES} x {formatCents(example.centsPerObjectType)} = {formatCents(example.totalCents)}
            </dd>
          </div>
          <div>
            <dt>Each later search</dt>
            <dd>$0.00</dd>
          </div>
        </dl>
        <p className="welcome-note">
          A very short clip is counted as at least {MINIMUM_FRAMES} frames ({minimumSeconds} seconds at {INDEX_FPS} fps), so
          each object type costs at least {formatCents(minimumCents)}. The figures are an estimate, not a quote.
        </p>
      </div>
    </Section>
  );
}
