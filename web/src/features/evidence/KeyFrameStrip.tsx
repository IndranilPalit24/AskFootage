import type { Clip } from '../../api/generated/types';
import { useApiClient } from '../../app/ApiContext';
import { ClipThumb } from '../../components/ClipThumb';
import { clipMomentTime } from '../../lib/time';

interface KeyFrameStripProps {
  clip: Clip;
  selected: number | null;
  onSelect: (index: number) => void;
}

/**
 * One button per key moment, named by its wall-clock time; choosing one seeks the player there. A moment
 * with a still shows it; one without is just its time (no empty picture box).
 */
export function KeyFrameStrip({ clip, selected, onSelect }: KeyFrameStripProps) {
  const client = useApiClient();
  if (clip.keyFrames.length === 0) return null;
  return (
    <section aria-labelledby="keyframes-heading" className="stack stack--tight">
      <h2 id="keyframes-heading" className="label">
        Key frames
      </h2>
      <ul className="keyframes" aria-labelledby="keyframes-heading">
        {clip.keyFrames.map((frame, index) => (
          <li key={`${frame.atSeconds}-${index}`}>
            <button
              type="button"
              className={frame.imageUrl ? 'keyframe' : 'keyframe keyframe--plain'}
              aria-pressed={selected === index}
              onClick={() => onSelect(index)}
            >
              {frame.imageUrl ? <ClipThumb url={client.assetUrl(frame.imageUrl)} /> : null}
              <span>{clipMomentTime(clip, frame.atSeconds)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
