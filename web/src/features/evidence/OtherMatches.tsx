import { Link } from 'react-router-dom';
import type { Clip } from '../../api/generated/types';
import { useApiClient } from '../../app/ApiContext';
import { ClipThumb, clipPosterPath } from '../../components/ClipThumb';
import { clipDuration, formatClipRange, formatDuration } from '../../lib/time';

/** The rest of the last search's matches, as a compact list with their real stills. Nothing when there are none. */
export function OtherMatches({ clips, cameraNames }: { clips: readonly Clip[]; cameraNames: ReadonlyMap<string, string> }) {
  const client = useApiClient();
  if (clips.length === 0) return null;
  return (
    <section aria-labelledby="other-matches-heading" className="card card--padded stack stack--tight">
      <h2 id="other-matches-heading" className="label">
        Other matches
      </h2>
      <ul className="other-matches">
        {clips.map((clip) => {
          const poster = clipPosterPath(clip);
          return (
            <li key={clip.id}>
              <Link to={`/clip/${encodeURIComponent(clip.id)}`} className="other-match">
                <ClipThumb url={poster === null ? null : client.assetUrl(poster)} duration={formatDuration(clipDuration(clip))} />
                <span className="other-match__text">
                  <span className="other-match__label">{clip.label}</span>
                  <span className="mono muted">
                    {formatClipRange(clip)} · {cameraNames.get(clip.camera) ?? clip.camera}
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
