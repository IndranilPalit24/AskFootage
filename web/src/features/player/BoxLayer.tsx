import { useCallback, useEffect, useState } from 'react';
import type { RecordingBoxes } from '../../api/generated/types';
import { boxesAt, type OverlayBox } from './boxOverlay';

interface BoxOverlayProps {
  boxes: RecordingBoxes;
  video: HTMLVideoElement | null;
}

const VIDEO_EVENTS = ['timeupdate', 'seeking', 'seeked', 'pause', 'ended', 'loadedmetadata', 'resize'] as const;

const NONE: OverlayBox[] = [];

function sameBoxes(a: readonly OverlayBox[], b: readonly OverlayBox[]): boolean {
  return (
    a.length === b.length &&
    a.every((box, index) => {
      const other = b[index]!;
      return (
        box.trackId === other.trackId &&
        box.role === other.role &&
        box.left === other.left &&
        box.top === other.top &&
        box.width === other.width &&
        box.height === other.height
      );
    })
  );
}

/**
 * The boxes over a playing video: red outlines for objects, a neutral outline for the person (only when
 * there is an object). It follows the video's clock while playing (animation frames) and re-reads it on
 * seeks, pauses and size changes. Pointer events pass through to the video controls.
 */
export function BoxOverlay({ boxes, video }: BoxOverlayProps) {
  const [drawn, setDrawn] = useState<OverlayBox[]>(NONE);

  const update = useCallback(() => {
    if (!video) return;
    const { width, height } = video.getBoundingClientRect();
    const next = boxesAt(boxes, video.currentTime, { width, height }, { width: video.videoWidth, height: video.videoHeight });
    setDrawn((current) => (sameBoxes(current, next) ? current : next.length === 0 ? NONE : next));
  }, [boxes, video]);

  useEffect(() => {
    if (!video) return;
    let frameRequest = 0;
    const tick = () => {
      update();
      frameRequest = window.requestAnimationFrame(tick);
    };
    const stop = () => {
      window.cancelAnimationFrame(frameRequest);
      frameRequest = 0;
    };
    const start = () => {
      if (frameRequest === 0) frameRequest = window.requestAnimationFrame(tick);
    };
    const onPause = () => {
      stop();
      update();
    };

    for (const name of VIDEO_EVENTS) video.addEventListener(name, update);
    video.addEventListener('play', start);
    video.addEventListener('playing', start);
    video.addEventListener('pause', onPause);
    video.addEventListener('ended', onPause);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    observer?.observe(video);
    document.addEventListener('fullscreenchange', update);

    update();
    if (!video.paused && !video.ended) start();

    return () => {
      stop();
      for (const name of VIDEO_EVENTS) video.removeEventListener(name, update);
      video.removeEventListener('play', start);
      video.removeEventListener('playing', start);
      video.removeEventListener('pause', onPause);
      video.removeEventListener('ended', onPause);
      observer?.disconnect();
      document.removeEventListener('fullscreenchange', update);
    };
  }, [video, update]);

  return (
    <div className="box-overlay" data-testid="box-overlay">
      {drawn.map((box) => (
        <div
          key={`${box.role}-${box.trackId}`}
          className={`box-overlay__box box-overlay__box--${box.role}`}
          data-testid={`box-overlay-${box.role}`}
          role="img"
          aria-label={`${box.label} outlined on the video`}
          style={{ left: box.left, top: box.top, width: box.width, height: box.height }}
        />
      ))}
    </div>
  );
}
