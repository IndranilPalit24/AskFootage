import { Link, useParams } from 'react-router-dom';
import { useApiClient } from '../app/ApiContext';
import { VideoPlayer } from '../features/player/VideoPlayer';
import { useRecordingBoxes } from '../features/player/useRecordingBoxes';

/** One whole recording in the player, with the stored boxes drawn over it. No clip data is needed. */
export function RecordingPlayerScreen() {
  const { id = '' } = useParams();
  const client = useApiClient();
  const boxes = useRecordingBoxes(id);

  return (
    <article aria-labelledby="recording-title">
      <Link to="/cameras" className="back-link">
        <span aria-hidden="true">← </span>
        All cameras
      </Link>
      <div className="page-head">
        <div>
          <h1 id="recording-title">Recording</h1>
          <p className="page-head__subtitle">{id}</p>
        </div>
      </div>
      <VideoPlayer
        src={client.recordingVideoUrl(id)}
        label={`Recording ${id}`}
        hint="This recording has no footage file to play."
        boxes={boxes}
      />
      <p className="footnote">The object being tracked is outlined in red while it is in view.</p>
    </article>
  );
}
