import { useRef, useState, type ChangeEvent } from 'react';
import { errorMessage } from '../../api/errors';
import { useApiClient } from '../../app/ApiContext';

type UploadState =
  | { kind: 'idle' }
  | { kind: 'uploading'; name: string }
  | { kind: 'done'; name: string }
  | { kind: 'error'; message: string };

interface AddRecordingButtonProps {
  day: string;
  camera: string;
  /** Called after the server accepted the file, so the list and day counts can refresh. */
  onAdded: () => void;
}

/** "Add footage": picks an MP4 and uploads it to the selected day. The outcome shows in a polite live region. */
export function AddRecordingButton({ day, camera, onAdded }: AddRecordingButtonProps) {
  const client = useApiClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>({ kind: 'idle' });

  async function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Clear the input so choosing the same file again still fires a change.
    event.target.value = '';
    if (!file) return;
    setState({ kind: 'uploading', name: file.name });
    try {
      await client.addRecording(file, day, camera);
      setState({ kind: 'done', name: file.name });
      onAdded();
    } catch (error) {
      setState({ kind: 'error', message: errorMessage(error) });
    }
  }

  let message = '';
  if (state.kind === 'uploading') message = `Adding ${state.name}…`;
  else if (state.kind === 'done') message = `Added ${state.name}. It is waiting to be processed.`;
  else if (state.kind === 'error') message = state.message;

  return (
    <div className="page-head__actions">
      <button
        type="button"
        className="btn"
        aria-disabled={state.kind === 'uploading' || undefined}
        onClick={() => {
          if (state.kind !== 'uploading') inputRef.current?.click();
        }}
      >
        Add footage
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="video/mp4"
        hidden
        tabIndex={-1}
        aria-label="Footage file (MP4)"
        onChange={handleChange}
      />
      <p className={state.kind === 'error' ? 'upload-status error-text' : 'upload-status muted'} aria-live="polite">
        {message}
      </p>
    </div>
  );
}
