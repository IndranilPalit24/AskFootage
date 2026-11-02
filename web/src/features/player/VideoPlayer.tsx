import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type Ref } from 'react';
import type { RecordingBoxes } from '../../api/generated/types';
import { FOOTAGE_NOT_INCLUDED } from '../../api/errors';
import { BoxOverlay } from './BoxLayer';
import { Scrubber } from './Scrubber';

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
  /** The matched interval (seconds from the start of the recording), highlighted on the scrubber. */
  matchStart?: number;
  matchEnd?: number;
  /** Event markers on the scrubber (key frames), in seconds from the start of the recording. */
  markers?: readonly number[];
  /** The recording's length, for the scrubber until the video reports its own. */
  lengthHint?: number;
  /**
   * Set when the recording is known to have no video behind it: this note is shown in the player area, and
   * the video is never requested.
   */
  unavailableNote?: string;
}

/** What a recording without a video says, in the player area and wherever else it is explained. */
export const NOT_INCLUDED_NOTE = 'Footage not included in this demo build';

/**
 * Why a video did not load. The element only says "error", so ask the server for one byte (CORS allows Range)
 * and turn the answer into a sentence a person can act on.
 */
export async function explainVideoFailure(src: string, signal?: AbortSignal): Promise<string | null> {
  try {
    const response = await fetch(src, { headers: { Range: 'bytes=0-0' }, signal });
    if (response.status === 404) {
      // The standard error body names a recording without a video; it is small, so it is read.
      const body: unknown = await response.json().catch(() => null);
      const code = (body as { error?: { code?: unknown } } | null)?.error?.code;
      if (code === FOOTAGE_NOT_INCLUDED) return NOT_INCLUDED_NOTE;
    }
    // Only the headers matter. A server that ignores Range answers 200 with the whole file: stop reading it.
    void response.body?.cancel().catch(() => undefined);
    if (response.status === 404) return 'The server has no video file for this recording (404). Check that the footage is on the server.';
    if (response.status >= 500) return `The server could not read the video (status ${response.status}).`;
    if (!response.ok) return `The server refused the video request (status ${response.status}).`;
    return 'The server sent the file but the browser could not play it. It may be damaged or in an unsupported format.';
  } catch {
    // Cancelled (a new attempt, or the player went away): there is no answer to show.
    if (signal?.aborted) return null;
    return 'The API could not be reached, so the video could not be loaded.';
  }
}

/** Seconds a left or right arrow jumps, and J or L. */
const ARROW_STEP = 5;
const JUMP_STEP = 10;

function assignRef(ref: Ref<HTMLVideoElement> | undefined, value: HTMLVideoElement | null) {
  if (typeof ref === 'function') ref(value);
  else if (ref) ref.current = value;
}

/**
 * Keys that belong to the element the person is on: the player must not take them. That includes the focused
 * <video> itself, whose native controls handle space and the arrows (so they are never handled twice).
 * The range scrubber is the exception on purpose: its arrow keys seek 5 s like everywhere else in the player,
 * instead of the slider's own 0.1 s step.
 */
function ownsKeys(target: EventTarget): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLVideoElement) return true;
  return target.closest('button, a, select, textarea, input:not([type="range"])') !== null;
}

/**
 * A 16:9 player on a dark letterbox, with a scrubber under it and keyboard shortcuts (space or K: play and
 * pause, left and right: 5 s, J and L: 10 s). No URL, or a video that fails to load (404), shows a calm
 * placeholder instead of an error. The .player wrapper (not the video) is what goes full screen, so the
 * boxes stay on top of the picture.
 */
export function VideoPlayer({ src: wantedSrc, startAt = 0, label, hint, videoRef, boxes, matchStart, matchEnd, markers, lengthHint, unavailableNote }: VideoPlayerProps) {
  // A recording known to have no video is never requested: the same as having no address.
  const src = unavailableNote ? null : wantedSrc;
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  // Bumping the attempt reloads the same address from scratch.
  const [attempt, setAttempt] = useState(0);
  // The request that explains a failure: cancelled by a new attempt or when the player goes away.
  const explaining = useRef<AbortController | null>(null);
  useEffect(() => () => explaining.current?.abort(), []);
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const hintId = useId();
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

  function handleVideoError(failed: string) {
    setFailedSrc(failed);
    setReason(null);
    explaining.current?.abort();
    const controller = new AbortController();
    explaining.current = controller;
    void explainVideoFailure(failed, controller.signal).then((text) => {
      if (!controller.signal.aborted && text !== null) setReason(text);
    });
  }

  function retry() {
    explaining.current?.abort();
    setFailedSrc(null);
    setReason(null);
    setAttempt((count) => count + 1);
  }

  function toggleFullscreen() {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const request = document.fullscreenElement ? document.exitFullscreen?.() : wrapper.requestFullscreen?.();
    // A refused request (no permission, not supported) leaves the player as it is.
    request?.catch(() => undefined);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!video || event.altKey || event.ctrlKey || event.metaKey || ownsKeys(event.target)) return;
    const seek = (delta: number) => {
      const end = Number.isFinite(video.duration) ? video.duration : Number.POSITIVE_INFINITY;
      video.currentTime = Math.min(Math.max(video.currentTime + delta, 0), end);
    };
    switch (event.key) {
      case ' ':
      case 'k':
      case 'K':
        if (video.paused) video.play()?.catch(() => undefined);
        else video.pause();
        break;
      case 'ArrowLeft':
        seek(-ARROW_STEP);
        break;
      case 'ArrowRight':
        seek(ARROW_STEP);
        break;
      case 'j':
      case 'J':
        seek(-JUMP_STEP);
        break;
      case 'l':
      case 'L':
        seek(JUMP_STEP);
        break;
      default:
        return;
    }
    event.preventDefault();
  }

  if (showPlaceholder) {
    return (
      <div className="stage">
        <div className="player">
          <div className="player__placeholder">
            <strong>{unavailableNote ?? (reason === NOT_INCLUDED_NOTE && failedSrc === src ? NOT_INCLUDED_NOTE : 'Footage file not attached')}</strong>
            {failedSrc === src && src !== null && reason !== NOT_INCLUDED_NOTE ? (
              <>
                <span className="small" role="status">
                  {reason ?? 'Checking why the video did not load…'}
                </span>
                <button type="button" className="btn btn--sm player__retry" onClick={retry}>
                  Try again
                </button>
              </>
            ) : null}
            {hint ? <span className="small">{hint}</span> : null}
          </div>
        </div>
      </div>
    );
  }

  return (
    // The stage takes the keyboard (Tab to it) for the shortcuts; it is a group, not a widget with its own role.
    <div className="stage" role="group" aria-label={`Player: ${label}`} aria-describedby={hintId} tabIndex={0} onKeyDown={handleKeyDown}>
      <div className="player" ref={wrapperRef}>
        <video
          key={attempt}
          ref={attachVideo}
          src={src}
          controls
          controlsList="nofullscreen"
          preload="metadata"
          aria-label={label}
          onLoadedMetadata={(event) => {
            if (startAt > 0) event.currentTarget.currentTime = startAt;
          }}
          onError={() => handleVideoError(src)}
        />
        {boxes ? <BoxOverlay boxes={boxes} video={video} /> : null}
        <button type="button" className="player__fullscreen" aria-pressed={fullscreen} onClick={toggleFullscreen}>
          Full screen
        </button>
      </div>
      <Scrubber video={video} matchStart={matchStart} matchEnd={matchEnd} markers={markers} lengthHint={lengthHint} />
      <p id={hintId} className="visually-hidden">
        Keyboard shortcuts: space or K plays and pauses, left and right arrows jump 5 seconds, J and L jump 10 seconds.
      </p>
      <ul className="shortcut-hint" aria-hidden="true">
        <li>
          <kbd>Space</kbd> play / pause
        </li>
        <li>
          <kbd>←</kbd> <kbd>→</kbd> 5 s
        </li>
        <li>
          <kbd>J</kbd> <kbd>K</kbd> <kbd>L</kbd> back / pause / forward
        </li>
      </ul>
    </div>
  );
}
