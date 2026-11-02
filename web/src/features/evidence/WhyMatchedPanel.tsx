import type { Clip, ClipProof } from '../../api/generated/types';
import { Chip } from '../../components/Chip';
import { clipDuration, formatClipRange, formatDuration } from '../../lib/time';
import { formatShortDay } from '../../lib/dates';
import { EvidenceChips } from './EvidenceChips';
import { objectsFromEvidence } from './objects';
import { formatSeconds, formatValue, measureLabel, RELATION_LABELS } from './ProofPanel';

/**
 * "Why this matched", the lead of the evidence rail: the reason in plain words, then the facts a reviewer
 * checks (relation, time range, camera and day), the evidence chips, the zone and the matched objects.
 * The contract has no object positions, so objects are listed as outlined neutral labels (person, box)
 * rather than drawn as boxes on the frame. Never a name, a face or anything that identifies someone.
 */
export function WhyMatchedPanel({ clip, cameraName, proof }: { clip: Clip; cameraName: string; proof?: ClipProof }) {
  const objects = objectsFromEvidence(clip.evidence);
  const relation = clip.evidence[0] ? RELATION_LABELS[clip.evidence[0].kind] : null;
  return (
    <section className="card card--padded why" aria-labelledby="why-heading">
      <h2 id="why-heading">Why this matched</h2>
      <p className="why__reason">{clip.whyMatched}</p>
      <dl className="facts-grid">
        {relation ? (
          <>
            <dt>Relation</dt>
            <dd>{relation}</dd>
          </>
        ) : null}
        <dt>Time range</dt>
        <dd className="mono">{formatClipRange(clip)}</dd>
        <dt>Length</dt>
        <dd className="mono">{formatDuration(clipDuration(clip))}</dd>
        <dt>Camera</dt>
        <dd>{cameraName}</dd>
        <dt>Day</dt>
        <dd>{formatShortDay(clip.day)}</dd>
      </dl>
      {proof ? (
        // Measured by the server for this match; shown as it sent them, never rescored here.
        <dl className="facts-grid" aria-label="Measurements">
          <dt>Seen in the recording</dt>
          <dd>
            {formatSeconds(proof.startSeconds)} to {formatSeconds(proof.endSeconds)}
          </dd>
          {proof.measures.map((measure) => (
            <div key={measure.name} className="facts-grid__pair">
              <dt>{measureLabel(measure.name)}</dt>
              <dd>{formatValue(measure.value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
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
