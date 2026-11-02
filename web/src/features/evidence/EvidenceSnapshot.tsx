import { useState } from 'react';

interface EvidenceSnapshotProps {
  /** The resolved image URL, or null when the clip has no snapshot. */
  src: string | null;
}

/** The frame where the match began, with the boxes drawn on it. Renders nothing without a snapshot. */
export function EvidenceSnapshot({ src }: EvidenceSnapshotProps) {
  const [failed, setFailed] = useState(false);
  if (src === null) return null;
  return (
    <section aria-labelledby="snapshot-heading" className="stack stack--tight">
      <h2 id="snapshot-heading">Evidence snapshot</h2>
      {failed ? (
        <p className="muted">The snapshot could not be loaded.</p>
      ) : (
        <figure className="snapshot">
          <img
            className="snapshot__image"
            src={src}
            alt="Frame where the match began, with the box in red and the person in grey"
            loading="lazy"
            onError={() => setFailed(true)}
          />
          <figcaption className="muted">Box in red, person in grey</figcaption>
        </figure>
      )}
    </section>
  );
}
