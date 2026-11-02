import { useState } from 'react';
import type { Clip } from '../api/generated/types';

/**
 * The still to show for a clip: its poster frame (a real still of the footage), else its thumbnail, else the
 * evidence snapshot. Null when the server has none of them.
 */
export function clipPosterPath(clip: Pick<Clip, 'posterUrl' | 'thumbnailUrl' | 'snapshotUrl'>): string | null {
  return clip.posterUrl ?? clip.thumbnailUrl ?? clip.snapshotUrl ?? null;
}

interface ClipThumbProps {
  /** A resolved image URL, or null when there is none. */
  url: string | null;
  /** Length chip in the corner, e.g. "0:04". */
  duration?: string;
  /** What to say when there is no image (default "No preview"). An image that fails to load says "Preview unavailable". */
  emptyText?: string;
}

/**
 * A 16:9 poster frame. With no image, or an image that fails to load, it is a neutral dark tile that says
 * "No preview": never an empty box and never a made-up picture.
 */
export function ClipThumb({ url, duration, emptyText = 'No preview' }: ClipThumbProps) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showImage = url !== null && failedUrl !== url;
  return (
    <div className="thumb">
      {showImage ? (
        <img src={url} alt="" width={192} height={108} loading="lazy" onError={() => setFailedUrl(url)} />
      ) : (
        <span className="thumb__empty">{url !== null ? 'Preview unavailable' : emptyText}</span>
      )}
      {duration ? (
        <span className="thumb__duration">
          <span className="visually-hidden">Length </span>
          {duration}
        </span>
      ) : null}
    </div>
  );
}
