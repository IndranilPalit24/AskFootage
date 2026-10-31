import type { ClipProof, ProofRelation } from '../../api/generated/types';

const RELATION_LABELS: Record<ProofRelation, string> = {
  carrying: 'Carrying',
  in_zone: 'In zone',
  dwell: 'Waiting (dwell)',
};

const MEASURE_LABELS: Record<string, string> = {
  frames_together: 'Frames together',
  motion_agreement: 'Motion agreement',
  frames_inside: 'Frames inside',
  coverage: 'Coverage',
};

/** "frames_together" -> "Frames together" for names the UI does not know. */
function measureLabel(name: string): string {
  const known = MEASURE_LABELS[name];
  if (known) return known;
  const spaced = name.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function formatValue(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function formatSeconds(seconds: number): string {
  return `${Math.round(seconds * 10) / 10} s`;
}

/** The measured proof for one clip: which relation was found, over what time, and the numbers behind it. */
export function ProofPanel({ proof }: { proof: ClipProof }) {
  const titleId = `proof-title-${proof.clipId}`;
  return (
    <section className="proof" aria-labelledby={titleId}>
      <h3 className="proof__title" id={titleId}>
        Why this matched
      </h3>
      <p className="proof__range">
        {RELATION_LABELS[proof.relation]} · {formatSeconds(proof.startSeconds)} to {formatSeconds(proof.endSeconds)}{' '}
        into the recording
      </p>
      {proof.measures.length > 0 ? (
        <ul className="proof__measures" aria-label="Measures">
          {proof.measures.map((measure) => (
            <li key={measure.name}>
              {measureLabel(measure.name)}: {formatValue(measure.value)}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
