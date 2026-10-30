import type { Clip } from '../../api/generated/types';
import { Chip } from '../../components/Chip';
import { EvidenceChips } from './EvidenceChips';
import { objectsFromEvidence } from './objects';

/**
 * "Why this matched": the plain-English reason, the evidence chips, the zone and the matched objects.
 * The contract has no object positions, so objects are listed as outlined neutral labels (person, box)
 * rather than drawn as boxes on the frame. Never a name, a face or anything that identifies someone.
 */
export function WhyMatchedPanel({ clip }: { clip: Clip }) {
  const objects = objectsFromEvidence(clip.evidence);
  return (
    <section className="card card--padded why" aria-labelledby="why-heading">
      <h2 id="why-heading">Why this matched</h2>
      <p>{clip.whyMatched}</p>
      <EvidenceChips evidence={clip.evidence} />
      <div className="facts">
        {clip.zone ? (
          <p className="facts__row">
            <span className="facts__term">Zone:</span> <span>{clip.zone}</span>
          </p>
        ) : null}
        {objects.length > 0 ? (
          <div className="facts__row">
            <span className="facts__term" id="matched-objects">
              Matched objects:
            </span>
            <ul className="chip-list" aria-labelledby="matched-objects">
              {objects.map((object) => (
                <li key={object}>
                  <Chip>{object}</Chip>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}
