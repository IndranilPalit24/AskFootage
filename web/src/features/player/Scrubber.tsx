import { Icon } from '../../components/Icon';
import { formatDuration } from '../../lib/time';
import { useVideoClock } from './useVideoClock';

interface ScrubberProps {
  video: HTMLVideoElement | null;
  /** The matched interval, in seconds from the start of the recording; highlighted in the accent. */
  matchStart?: number;
  matchEnd?: number;
  /** Event markers (key frames), in seconds from the start of the recording. */
  markers?: readonly number[];
  /** The recording's length when the video has not reported it yet. */
  lengthHint?: number;
}

function percent(seconds: number, total: number): string {
  return `${Math.min(Math.max((seconds / total) * 100, 0), 100).toFixed(3)}%`;
}

/**
 * A scrubber under the player: play and pause, the current time, a track that shows where the match sits in
 * the recording (accent) and where its key moments are (ticks), and the length. Click or drag to seek; the
 * slider is a native range input, so the keyboard works too.
 */
export function Scrubber({ video, matchStart, matchEnd, markers = [], lengthHint }: ScrubberProps) {
  const { time, duration, playing } = useVideoClock(video);
  const total = Number.isFinite(duration) && duration > 0 ? duration : (lengthHint ?? matchEnd ?? 0);
  const hasMatch = matchStart !== undefined && matchEnd !== undefined && matchEnd > matchStart && total > 0;
  const position = Math.min(time, total);

  function toggle() {
    if (!video) return;
    if (video.paused) video.play()?.catch(() => undefined);
    else video.pause();
  }

  return (
    <div className="scrubber">
      <div className="scrubber__row">
        <button type="button" className="scrubber__play" aria-label={playing ? 'Pause' : 'Play'} onClick={toggle}>
          <Icon name={playing ? 'pause' : 'play'} size={16} />
        </button>
        <span className="scrubber__time" data-testid="scrubber-time">
          {formatDuration(position)}
        </span>
        <div className="scrubber__track">
          <span className="scrubber__rail" />
          {hasMatch ? (
            <span
              className="scrubber__match"
              data-testid="scrubber-match"
              style={{ left: percent(matchStart, total), width: percent(matchEnd - matchStart, total) }}
            />
          ) : null}
          {total > 0
            ? markers.map((at, index) => (
                <span key={`${at}-${index}`} className="scrubber__marker" aria-hidden="true" style={{ left: percent(at, total) }} />
              ))
            : null}
          <input
            type="range"
            className="scrubber__input"
            aria-label="Seek"
            aria-valuetext={`${formatDuration(position)} of ${formatDuration(total)}`}
            min={0}
            max={total}
            step={0.1}
            value={position}
            disabled={total <= 0}
            onChange={(event) => {
              if (video) video.currentTime = Number(event.target.value);
            }}
          />
        </div>
        <span className="scrubber__time scrubber__time--total">{formatDuration(total)}</span>
      </div>
      {hasMatch ? (
        <p className="scrubber__legend">
          <span>
            Matched interval <span className="mono">{formatDuration(matchStart)}–{formatDuration(matchEnd)}</span> in blue
          </span>
          <span>Click the track to seek</span>
        </p>
      ) : null}
    </div>
  );
}
