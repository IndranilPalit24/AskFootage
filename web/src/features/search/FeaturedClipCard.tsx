import { memo, useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import type { Clip, ClipProof } from '../../api/generated/types';
import { useApiClient } from '../../app/ApiContext';
import { Icon } from '../../components/Icon';
import { SaveClipButton } from '../../components/SaveClipButton';
import { useAsyncData } from '../../hooks/useAsyncData';
import { formatFullDay } from '../../lib/dates';
import { clipDuration, clipMomentTime, clipStartOfDay, formatClipRange, formatClock, formatDuration, formatTimeOfDay } from '../../lib/time';
import { clipPosterPath } from '../../components/ClipThumb';
import { BoxOverlay } from '../player/BoxLayer';
import { explainVideoFailure, NOT_INCLUDED_NOTE } from '../player/VideoPlayer';
import { useRecordingBoxes } from '../player/useRecordingBoxes';
import { useVideoClock } from '../player/useVideoClock';
import { RELATION_LABELS, formatSeconds, formatValue, measureLabel } from '../evidence/ProofPanel';

/** The rows of "Why this matched": only what the API returned for this clip, in plain words. */
export function whyRows(clip: Clip, proof: ClipProof | undefined): Array<[string, string]> {
  const rows: Array<[string, string]> = [];
  const relation = proof ? RELATION_LABELS[proof.relation] : clip.evidence[0] ? RELATION_LABELS[clip.evidence[0].kind] : null;
  if (relation) rows.push(['Relation', relation]);
  if (proof) {
    rows.push(['Seen in the recording', `${formatSeconds(proof.startSeconds)} to ${formatSeconds(proof.endSeconds)}`]);
    for (const measure of proof.measures) rows.push([measureLabel(measure.name), formatValue(measure.value)]);
  }
  if (clip.zone) rows.push(['Zone', clip.zone]);
  return rows;
}

function percent(seconds: number, total: number): string {
  return `${Math.min(Math.max((seconds / total) * 100, 0), 100).toFixed(3)}%`;
}

interface Props {
  clip: Clip;
  cameraName: string;
  proof?: ClipProof;
}

/**
 * The lead result: the real poster (or, once played, the real video with the stored boxes drawn over it),
 * the time range as its title, why it matched, a compact playback bar, and Open clip / Save clip.
 * The video is only requested when someone presses play.
 */
export const FeaturedClipCard = memo(function FeaturedClipCard({ clip, cameraName, proof }: Props) {
  const client = useApiClient();
  const frameRef = useRef<HTMLDivElement>(null);
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  // null: showing the poster. A number: the video is mounted and starts at that many seconds.
  const [startAt, setStartAt] = useState<number | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [posterFailed, setPosterFailed] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const labelId = `clip-label-${clip.id}`;
  const explaining = useRef<AbortController | null>(null);
  useEffect(() => () => explaining.current?.abort(), []);

  const recordings = useAsyncData(() => client.listRecordings(clip.day, clip.camera), ['recordings', clip.day, clip.camera]);
  const recording = recordings.data?.find((item) => item.id === clip.recordingId);
  const noFootage = recording?.hasFootage === false;
  const src = noFootage ? null : client.recordingVideoUrl(clip.recordingId);
  const active = startAt !== null && src !== null;
  const boxes = useRecordingBoxes(active ? clip.recordingId : null);
  const { time, duration, playing } = useVideoClock(video);
  const lengthHint = recording?.lengthSeconds && recording.lengthSeconds > 0 ? recording.lengthSeconds : clip.endSeconds;
  const total = Number.isFinite(duration) && duration > 0 ? duration : lengthHint;
  const position = active ? Math.min(time, total) : 0;
  const posterPath = clipPosterPath(clip);
  const posterUrl = posterPath === null ? null : client.assetUrl(posterPath);
  const start = clipStartOfDay(clip);
  const range = `${formatFullDay(clip.day)}, ${clip.startTime} – ${formatTimeOfDay(start + clipDuration(clip))}`;

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === frameRef.current && frameRef.current !== null);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const attach = useCallback((element: HTMLVideoElement | null) => setVideo(element), []);

  function play(at: number) {
    if (src === null) return;
    if (!active) {
      setFailure(null);
      setStartAt(at);
      return;
    }
    if (video) {
      video.currentTime = at;
      video.play()?.catch(() => undefined);
    }
  }

  function toggle() {
    if (!active) play(clip.startSeconds);
    else if (video?.paused) video.play()?.catch(() => undefined);
    else video?.pause();
  }

  function seek(at: number) {
    if (!active) setStartAt(at);
    else if (video) video.currentTime = at;
  }

  function videoFailed() {
    if (src === null) return;
    setFailure('Checking why the video did not load…');
    explaining.current?.abort();
    const controller = new AbortController();
    explaining.current = controller;
    void explainVideoFailure(src, controller.signal).then((text) => {
      if (!controller.signal.aborted && text !== null) setFailure(text);
    });
  }

  function retry() {
    explaining.current?.abort();
    setFailure(null);
    setAttempt((count) => count + 1);
  }

  function toggleFullscreen() {
    const frame = frameRef.current;
    if (!frame) return;
    const request = document.fullscreenElement ? document.exitFullscreen?.() : frame.requestFullscreen?.();
    request?.catch(() => undefined);
  }

  let media;
  if (noFootage) {
    media = <div className="clipframe__note">{NOT_INCLUDED_NOTE}</div>;
  } else if (failure !== null) {
    media = (
      <div className="clipframe__note" role="status">
        <strong>The video could not be played.</strong>
        <span>{failure}</span>
        <button type="button" className="btn btn--sm" onClick={retry}>
          Try again
        </button>
      </div>
    );
  } else if (active) {
    media = (
      <>
        <video
          key={attempt}
          ref={attach}
          className="clipframe__media"
          src={src}
          preload="metadata"
          playsInline
          aria-label={`${clip.label}, ${formatClipRange(clip)}`}
          onLoadedMetadata={(event) => {
            event.currentTarget.currentTime = startAt;
            event.currentTarget.play()?.catch(() => undefined);
          }}
          onError={videoFailed}
        />
        {boxes ? <BoxOverlay boxes={boxes} video={video} /> : null}
      </>
    );
  } else if (posterUrl !== null && !posterFailed) {
    media = <img className="clipframe__media" src={posterUrl} alt="" onError={() => setPosterFailed(true)} />;
  } else {
    media = (
      <div className="clipframe__note">
        <span>{posterUrl === null ? 'No preview' : 'Preview unavailable'}</span>
        {posterUrl !== null ? (
          <button type="button" className="btn btn--sm" onClick={() => setPosterFailed(false)}>
            Try again
          </button>
        ) : null}
      </div>
    );
  }

  const hasMatch = total > 0 && clip.endSeconds > clip.startSeconds;
  const matchStyle: CSSProperties | undefined = hasMatch
    ? { left: percent(clip.startSeconds, total), width: percent(clip.endSeconds - clip.startSeconds, total) }
    : undefined;
  // Camera-local clock time of the frame on screen.
  const stamp = clipMomentTime(clip, active ? position : clip.startSeconds);

  return (
    <li>
      <article className="card result" aria-labelledby={labelId}>
        <div className="result__media">
          <div className={fullscreen ? 'player clipframe clipframe--fullscreen' : 'player clipframe'} ref={frameRef}>
            {media}
            <span className="clipframe__caption clipframe__caption--start">
              {clip.camera} - {cameraName}
            </span>
            <span className="clipframe__caption clipframe__caption--end">
              {formatFullDay(clip.day)} {stamp}
            </span>
            {active && failure === null ? (
              <button type="button" className="player__fullscreen" aria-pressed={fullscreen} aria-label="Full screen" onClick={toggleFullscreen}>
                <Icon name="fullscreen" size={16} />
              </button>
            ) : null}
          </div>
        </div>
        <div className="result__body">
          <h2 className="result__title" id={labelId}>
            {range}
          </h2>
          <p className="result__camera">
            <span className="mono">{clip.camera}</span> {cameraName}
          </p>
          <p className="result__reason">{clip.whyMatched}</p>
          <div className="playbar">
            <button
              type="button"
              className="playbar__play"
              aria-label={playing ? 'Pause' : 'Play'}
              disabled={src === null}
              onClick={toggle}
            >
              <Icon name={playing ? 'pause' : 'play'} size={16} />
            </button>
            <div className="playbar__track">
              <span className="playbar__rail" />
              {matchStyle ? <span className="playbar__match" data-testid="playbar-match" style={matchStyle} /> : null}
              <input
                type="range"
                className="playbar__input"
                aria-label="Seek"
                aria-valuetext={`${formatDuration(position)} of ${formatDuration(total)}`}
                min={0}
                max={total > 0 ? total : 1}
                step={0.1}
                value={position}
                disabled={src === null || total <= 0}
                onChange={(event) => seek(Number(event.target.value))}
              />
            </div>
            <span className="playbar__time" data-testid="playbar-time">
              {formatClock(position)} / {formatClock(total)}
            </span>
          </div>
          {proof ? (
          <section className="why-box" aria-label="Why this matched">
            <h3>Why this matched</h3>
            <dl>
              {whyRows(clip, proof).map(([label, value]) => (
                <div key={label} className="why-box__row">
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </section>
          ) : null}
          <div className="btn-row result__actions">
            <Link to={`/clip/${encodeURIComponent(clip.id)}`} className="btn btn--primary" aria-describedby={labelId}>
              Open clip
              <Icon name="external" size={16} />
            </Link>
            <SaveClipButton clipId={clip.id} describedBy={labelId} />
          </div>
        </div>
      </article>
    </li>
  );
});
