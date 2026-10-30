import { useState, type Ref } from 'react';

interface VideoPlayerProps {
  /** Null when there is no footage to stream. */
  src: string | null;
  /** Seconds from the start of the recording to begin at. */
  startAt?: number;
  /** Accessible name of the video. */
  label: string;
  /** Extra line under the placeholder. */
  hint?: string;
  videoRef?: Ref<HTMLVideoElement>;
}

/** A 16:9 player. No URL, or a video that fails to load (404), shows a calm placeholder instead of an error. */
export function VideoPlayer({ src, startAt = 0, label, hint, videoRef }: VideoPlayerProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showPlaceholder = src === null || failedSrc === src;

  if (showPlaceholder) {
    return (
      <div className="player">
        <div className="player__placeholder">
          <strong>Footage file not attached</strong>
          {hint ? <span className="small">{hint}</span> : null}
        </div>
      </div>
    );
  }

  return (
    <div className="player">
      <video
        ref={videoRef}
        src={src}
        controls
        preload="metadata"
        aria-label={label}
        onLoadedMetadata={(event) => {
          if (startAt > 0) event.currentTarget.currentTime = startAt;
        }}
        onError={() => setFailedSrc(src)}
      />
    </div>
  );
}
