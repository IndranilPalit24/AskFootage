import { useEffect, useState } from 'react';

export interface VideoClock {
  /** Seconds into the recording. */
  time: number;
  /** Seconds, or NaN until the video knows its length. */
  duration: number;
  playing: boolean;
}

const EVENTS = ['timeupdate', 'seeking', 'seeked', 'loadedmetadata', 'durationchange', 'play', 'pause', 'ended'] as const;

const IDLE: VideoClock = { time: 0, duration: Number.NaN, playing: false };

/** The video's position, length and play state, kept in step by its own events. */
export function useVideoClock(video: HTMLVideoElement | null): VideoClock {
  const [clock, setClock] = useState<VideoClock>(IDLE);

  useEffect(() => {
    if (!video) return undefined;
    const sync = () => setClock({ time: video.currentTime, duration: video.duration, playing: !video.paused });
    sync();
    for (const name of EVENTS) video.addEventListener(name, sync);
    return () => {
      for (const name of EVENTS) video.removeEventListener(name, sync);
    };
  }, [video]);

  return clock;
}
