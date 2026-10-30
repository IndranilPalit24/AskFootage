import type { Clip } from '../../api/generated/types';
import { ClipThumb } from '../../components/ClipThumb';
import { clipMomentTime } from '../../lib/time';

interface KeyFrameStripProps {
  clip: Clip;
  selected: number | null;
  onSelect: (index: number) => void;
}

/** One button per key frame, named by its wall-clock time; choosing one seeks the player there. */
export function KeyFrameStrip({ clip, selected, onSelect }: KeyFrameStripProps) {
  if (clip.keyFrames.length === 0) return null;
  return (
    <section aria-labelledby="keyframes-heading" className="stack stack--tight">
      <h2 id="keyframes-heading">Key frames</h2>
      <ul className="keyframes" aria-labelledby="keyframes-heading">
        {clip.keyFrames.map((frame, index) => (
          <li key={`${frame.atSeconds}-${index}`}>
            <button
              type="button"
              className="keyframe"
              aria-pressed={selected === index}
              onClick={() => onSelect(index)}
            >
              <ClipThumb url={frame.imageUrl} />
              <span>{clipMomentTime(clip, frame.atSeconds)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
