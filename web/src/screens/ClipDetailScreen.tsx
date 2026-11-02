import { useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { Clip } from '../api/generated/types';
import { useApiClient } from '../app/ApiContext';
import { useSearchState } from '../app/SearchContext';
import { OtherMatches } from '../features/evidence/OtherMatches';
import { useAppData } from '../app/AppDataContext';
import { EmptyState } from '../components/EmptyState';
import { Icon } from '../components/Icon';
import { SaveClipButton } from '../components/SaveClipButton';
import { EvidenceSnapshot } from '../features/evidence/EvidenceSnapshot';
import { KeyFrameStrip } from '../features/evidence/KeyFrameStrip';
import { WhyMatchedPanel } from '../features/evidence/WhyMatchedPanel';
import { NOT_INCLUDED_NOTE, VideoPlayer } from '../features/player/VideoPlayer';
import { useRecordingBoxes } from '../features/player/useRecordingBoxes';
import { DayTimeline } from '../features/timeline/DayTimeline';
import { useAsyncData } from '../hooks/useAsyncData';
import { usePageTitle } from '../hooks/usePageTitle';
import { formatShortDay } from '../lib/dates';
import { clipDuration, clipStartOfDay, formatClipRange, formatHourMinute } from '../lib/time';

function BackLink() {
  return (
    <Link to="/" className="back-link">
      <Icon name="arrowLeft" size={16} />
      Back to results
    </Link>
  );
}

/**
 * The review workspace: the player on a dark letterbox with its scrubber on the left; on the right the
 * evidence rail (Save clip, why it matched, the snapshot). Under the player: key frames and the day timeline.
 */
function ClipDetail({ clip, cameraName }: { clip: Clip; cameraName: string }) {
  const client = useApiClient();
  // The clip's camera's recordings that day, for the timeline. It needs the clip, so it starts once the clip is here.
  const recordings = useAsyncData(
    () => client.listRecordings(clip.day, clip.camera),
    ['recordings', clip.day, clip.camera],
  );
  const boxes = useRecordingBoxes(clip.recordingId);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [selectedFrame, setSelectedFrame] = useState<number | null>(null);
  usePageTitle(clip.label);
  // The last search, when there is one: its measurements for this clip and its other matches.
  const search = useSearchState();
  const { cameras } = useAppData();
  const cameraNames = useMemo(() => new Map((cameras ?? []).map((camera) => [camera.id, camera.name])), [cameras]);
  // Only when the viewed clip is one of that search's results: otherwise the search is about something else.
  const inSearch = search.phase === 'done' && search.response.clips.some((item) => item.id === clip.id);
  const proof = inSearch ? search.response.proofs.find((item) => item.clipId === clip.id) : undefined;
  const others = inSearch ? search.response.clips.filter((item) => item.id !== clip.id) : [];

  function selectFrame(index: number) {
    setSelectedFrame(index);
    const frame = clip.keyFrames[index];
    const video = videoRef.current;
    if (frame && video) video.currentTime = frame.atSeconds;
  }

  const range = formatClipRange(clip);
  const matchStart = clipStartOfDay(clip);
  const titleId = 'clip-title';
  const recording = recordings.data?.find((item) => item.id === clip.recordingId);
  const recordingLength = recording?.lengthSeconds;
  // A clip is only ever a match of a recording that has footage; the list is checked as well, so a recording
  // without a video shows the note and never the player.
  const noFootage = recording?.hasFootage === false;

  return (
    <article className="workspace" aria-labelledby={titleId}>
      <BackLink />
      <div className="workspace__head">
        <h1 id={titleId}>{clip.label}</h1>
        <p className="workspace__meta">
          {formatShortDay(clip.day)} · {range} · {cameraName}
        </p>
      </div>

      <div className="workspace__grid">
        <div className="workspace__main">
          <VideoPlayer
            src={client.recordingVideoUrl(clip.recordingId)}
            unavailableNote={noFootage ? NOT_INCLUDED_NOTE : undefined}
            startAt={clip.startSeconds}
            label={`${clip.label}, ${range}`}
            hint="The evidence below is still available."
            videoRef={videoRef}
            boxes={boxes}
            matchStart={clip.startSeconds}
            matchEnd={clip.endSeconds}
            markers={clip.keyFrames.map((frame) => frame.atSeconds)}
            lengthHint={recordingLength && recordingLength > 0 ? recordingLength : undefined}
          />
          <KeyFrameStrip clip={clip} selected={selectedFrame} onSelect={selectFrame} />
          <DayTimeline
            recordings={recordings.data ?? []}
            matchStart={matchStart}
            matchEnd={matchStart + clipDuration(clip)}
            label={`Matched at ${formatHourMinute(clip.startTime)} on ${formatShortDay(clip.day)}`}
          />
        </div>
        <aside className="rail" aria-label="Evidence">
          <SaveClipButton clipId={clip.id} primary />
          <Link to={`/recordings/${encodeURIComponent(clip.recordingId)}`} className="btn">
            Open full recording
          </Link>
          <WhyMatchedPanel clip={clip} cameraName={cameraName} proof={proof} />
          <EvidenceSnapshot src={clip.snapshotUrl === null ? null : client.assetUrl(clip.snapshotUrl)} />
          <OtherMatches clips={others} cameraNames={cameraNames} />
        </aside>
      </div>
    </article>
  );
}

/** The workspace's shape while the clip loads: the dark stage and the rail, as skeletons. */
const loadingWorkspace = (
  <div className="workspace">
    <BackLink />
    <p className="visually-hidden" role="status">
      Loading clip…
    </p>
    <div className="workspace__grid" aria-hidden="true">
      <div className="workspace__main">
        <span className="skeleton skeleton--title" />
        <span className="skeleton skeleton--stage" />
      </div>
      <div className="rail">
        <span className="skeleton skeleton--line" />
        <span className="skeleton skeleton--line skeleton--short" />
        <span className="skeleton skeleton--line" />
      </div>
    </div>
  </div>
);

export function ClipDetailScreen() {
  const { id = '' } = useParams();
  const client = useApiClient();
  const { cameras } = useAppData();
  const clip = useAsyncData(() => client.getClip(id), ['clip', id]);
  usePageTitle(clip.data ? undefined : 'Clip');

  if (clip.error && !clip.data) {
    // An unknown or malformed id is "not found" to the person, whatever code the server used.
    const missing = clip.error.code === 'not_found' || clip.error.code === 'validation_error';
    return (
      <div className="stack">
        <BackLink />
        {missing ? (
          <EmptyState
            headingLevel={1}
            title="Clip not found."
            action={
              <Link to="/" className="btn btn--primary">
                Go to Find Footage
              </Link>
            }
          >
            It may belong to a search you have not run yet. Ask again from Find Footage to get a fresh result.
          </EmptyState>
        ) : (
          <EmptyState
            tone="error"
            title="The clip could not be loaded"
            action={
              <button type="button" className="btn" onClick={clip.reload}>
                Try again
              </button>
            }
          >
            <span className="error-text">{clip.error.message}</span>
          </EmptyState>
        )}
      </div>
    );
  }

  if (!clip.data || !cameras) return loadingWorkspace;

  const cameraId = clip.data.camera;
  const cameraName = cameras.find((camera) => camera.id === cameraId)?.name ?? cameraId;
  return <ClipDetail key={clip.data.id} clip={clip.data} cameraName={cameraName} />;
}
