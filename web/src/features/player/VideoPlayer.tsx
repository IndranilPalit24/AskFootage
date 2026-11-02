import { useCallback, useEffect, useRef, useState, type Ref } from 'react';
import type { RecordingBoxes } from '../../api/generated/types';
import { BoxOverlay } from './BoxLayer';

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
  /** The recording's stored boxes, drawn over the video as it plays. Left out or null: no overlay. */
  boxes?: RecordingBoxes | null;
}

function assignRef(ref: Ref<HTMLVideoElement> | undefined, value: HTMLVideoElement | null) {
  if (typeof ref === 'function') ref(value);
  else if (ref) ref.current = value;
}

/**
 * A 16:9 player. No URL, or a video that fails to load (404), shows a calm placeholder instead of an error.
 * The .player wrapper (not the video) is what goes full screen, so the boxes stay on top of the picture.
 */
export function VideoPlayer({ src, startAt = 0, label, hint, videoRef, boxes }: VideoPlayerProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const showPlaceholder = src === null || failedSrc === src;

  const attachVideo = useCallback(
    (element: HTMLVideoElement | null) => {
      setVideo(element);
      assignRef(videoRef, element);
    },
    [videoRef],
  );

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === wrapperRef.current && wrapperRef.current !== null);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  function toggleFullscreen() {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const request = document.fullscreenElement ? document.exitFullscreen?.() : wrapper.requestFullscreen?.();
    // A refused request (no permission, not supported) leaves the player as it is.
    request?.catch(() => undefined);
  }

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
    <div className="player" ref={wrapperRef}>
      <video
        ref={attachVideo}
        src={src}
        controls
        controlsList="nofullscreen"
        preload="metadata"
        aria-label={label}
        onLoadedMetadata={(event) => {
          if (startAt > 0) event.currentTarget.currentTime = startAt;
        }}
        onError={() => setFailedSrc(src)}
      />
      {boxes ? <BoxOverlay boxes={boxes} video={video} /> : null}
      <button
        type="button"
        className="player__fullscreen"
        aria-pressed={fullscreen}
        onClick={toggleFullscreen}
      >
        Full screen
      </button>
    </div>
  );
}
