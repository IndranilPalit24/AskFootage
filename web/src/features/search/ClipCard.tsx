import { memo } from 'react';
import { Link } from 'react-router-dom';
import type { Clip } from '../../api/generated/types';
import { ClipThumb } from '../../components/ClipThumb';
import { SaveClipButton } from '../../components/SaveClipButton';
import { formatClipRange } from '../../lib/time';
import { EvidenceChips } from '../evidence/EvidenceChips';

/** One result: the still, the time range, the label, the evidence, and Open / Save clip. */
export const ClipCard = memo(function ClipCard({ clip }: { clip: Clip }) {
  const labelId = `clip-label-${clip.id}`;
  return (
    <li>
      <article className="card clip-card" aria-labelledby={labelId}>
        <ClipThumb url={clip.thumbnailUrl} />
        <div className="clip-card__body">
          <p className="clip-card__time">{formatClipRange(clip)}</p>
          <h2 className="clip-card__label" id={labelId} title={clip.label}>
            {clip.label}
          </h2>
          <EvidenceChips evidence={clip.evidence} />
          <div className="btn-row clip-card__actions">
            <Link to={`/clip/${encodeURIComponent(clip.id)}`} className="btn btn--sm" aria-describedby={labelId}>
              Open
            </Link>
            <SaveClipButton clipId={clip.id} describedBy={labelId} small />
          </div>
        </div>
      </article>
    </li>
  );
});
