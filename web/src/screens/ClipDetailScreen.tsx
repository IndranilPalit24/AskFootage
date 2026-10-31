import { useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { Clip } from '../api/generated/types';
import { useApiClient } from '../app/ApiContext';
import { useAppData } from '../app/AppDataContext';
import { SaveClipButton } from '../components/SaveClipButton';
import { KeyFrameStrip } from '../features/evidence/KeyFrameStrip';
import { WhyMatchedPanel } from '../features/evidence/WhyMatchedPanel';
import { VideoPlayer } from '../features/player/VideoPlayer';
import { DayTimeline } from '../features/timeline/DayTimeline';
import { useAsyncData } from '../hooks/useAsyncData';
import { formatShortDay } from '../lib/dates';
import { clipDuration, clipStartOfDay, formatClipRange, formatHourMinute } from '../lib/time';

function BackLink() {
  return (
    <Link to="/" className="back-link">
      <span aria-hidden="true">← </span>
      Back to results
    </Link>
  );
}

function ClipDetail({ clip, cameraName }: { clip: Clip; cameraName: string }) {
  const client = useApiClient();
  // The clip's camera's recordings that day, for the timeline. It needs the clip, so it starts once the clip is here.
  const recordings = useAsyncData(
    () => client.listRecordings(clip.day, clip.camera),
    ['recordings', clip.day, clip.camera],
  );
  const videoRef = useRef<HTMLVideoElement>(null);
  const [selectedFrame, setSelectedFrame] = useState<number | null>(null);

  function selectFrame(index: number) {
    setSelectedFrame(index);
    const frame = clip.keyFrames[index];
    const video = videoRef.current;
    if (frame && video) video.currentTime = frame.atSeconds;
  }

  const range = formatClipRange(clip);
  const matchStart = clipStartOfDay(clip);
  const titleId = 'clip-title';

  return (
    <article aria-labelledby={titleId}>
      <BackLink />
      <div className="page-head">
        <div>
          <h1 id={titleId}>{clip.label}</h1>
          <p className="page-head__subtitle">
            {formatShortDay(clip.day)} · {range} · {cameraName}
          </p>
        </div>
        <div className="page-head__actions">
          <SaveClipButton clipId={clip.id} />
        </div>
      </div>

      <div className="detail-grid">
        <div className="stack">
          <VideoPlayer
            src={client.recordingVideoUrl(clip.recordingId)}
            startAt={clip.startSeconds}
            label={`${clip.label}, ${range}`}
            hint="The evidence below is still available."
            videoRef={videoRef}
          />
          <KeyFrameStrip clip={clip} selected={selectedFrame} onSelect={selectFrame} />
          <DayTimeline
            recordings={recordings.data ?? []}
            matchStart={matchStart}
            matchEnd={matchStart + clipDuration(clip)}
            label={`Matched at ${formatHourMinute(clip.startTime)} on ${formatShortDay(clip.day)}`}
          />
        </div>
        <WhyMatchedPanel clip={clip} />
      </div>
    </article>
  );
}

export function ClipDetailScreen() {
  const { id = '' } = useParams();
  const client = useApiClient();
  const { cameras } = useAppData();
  const clip = useAsyncData(() => client.getClip(id), ['clip', id]);

  if (clip.error && !clip.data) {
    // An unknown or malformed id is "not found" to the person, whatever code the server used.
    const missing = clip.error.code === 'not_found' || clip.error.code === 'validation_error';
    return (
      <div className="stack">
        <BackLink />
        {missing ? (
          <h1>Clip not found.</h1>
        ) : (
          <div role="alert">
            <p className="error-text">{clip.error.message}</p>
            <p className="results-status__action">
              <button type="button" className="btn" onClick={clip.reload}>
                Try again
              </button>
            </p>
          </div>
        )}
      </div>
    );
  }

  if (!clip.data || !cameras) {
    return (
      <div className="stack">
        <BackLink />
        <p className="muted" role="status">
          Loading clip…
        </p>
      </div>
    );
  }

  const cameraId = clip.data.camera;
  const cameraName = cameras.find((camera) => camera.id === cameraId)?.name ?? cameraId;
  return <ClipDetail key={clip.data.id} clip={clip.data} cameraName={cameraName} />;
}
