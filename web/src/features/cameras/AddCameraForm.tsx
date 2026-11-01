import { useId, useRef, useState, type FormEvent, type Ref } from 'react';
import { maskedRtspUrlPreview } from '../../api/cameraRules';
import { ApiError, errorMessage } from '../../api/errors';
import type { Camera } from '../../api/generated/types';
import { useApiClient } from '../../app/ApiContext';
import { useToasts } from '../../app/ToastContext';
import {
  cameraCreateBody,
  cameraFormErrors,
  EMPTY_CAMERA_FORM,
  type CameraFormField,
  type CameraFormValues,
} from './cameraForm';

interface TextFieldProps {
  field: CameraFormField;
  label: string;
  required?: boolean;
  type?: 'text' | 'password';
  /** An uncontrolled input never copies what is typed into the page's markup (used for the password). */
  uncontrolled?: boolean;
  value: string;
  error: string | undefined;
  hint?: string;
  inputRef?: Ref<HTMLInputElement>;
  onChange: (field: CameraFormField, value: string) => void;
  onBlur: (field: CameraFormField) => void;
}

function TextField({
  field,
  label,
  required = false,
  type = 'text',
  uncontrolled = false,
  value,
  error,
  hint,
  inputRef,
  onChange,
  onBlur,
}: TextFieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ') || undefined;
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
        {required ? (
          <span aria-hidden="true"> *</span>
        ) : (
          <span className="muted"> (optional)</span>
        )}
      </label>
      <input
        id={id}
        ref={inputRef}
        className="input"
        type={type}
        required={required}
        autoComplete={type === 'text' ? 'off' : 'new-password'}
        spellCheck={false}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...(uncontrolled ? {} : { value })}
        onChange={(event) => onChange(field, event.target.value)}
        onBlur={() => onBlur(field)}
      />
      {hint ? (
        <p id={hintId} className="muted small">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="inline-error">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function costNote(count: number): string {
  const registered = count === 1 ? '1 camera registered.' : `${count} cameras registered.`;
  return `${registered} Indexing footage costs about $0.20 per 1,000 frames for each object type.`;
}

interface AddCameraFormProps {
  cameraCount: number;
  /** Runs the request as a write, so a list refresh cannot undo it. */
  write: <T>(action: () => Promise<T>) => Promise<T>;
  onAdded: (camera: Camera) => void;
}

export function AddCameraForm({ cameraCount, write, onAdded }: AddCameraFormProps) {
  const client = useApiClient();
  const toasts = useToasts();
  const [values, setValues] = useState<CameraFormValues>(EMPTY_CAMERA_FORM);
  const [touched, setTouched] = useState<ReadonlySet<CameraFormField>>(new Set());
  const [nameTaken, setNameTaken] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const passwordInput = useRef<HTMLInputElement>(null);
  const costId = useId();

  const errors = cameraFormErrors(values);
  const valid = Object.keys(errors).length === 0;
  const canSubmit = valid && values.acknowledgeCost && !submitting;
  const shown = (field: CameraFormField) => (touched.has(field) ? errors[field] : undefined);

  function change(field: CameraFormField, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    if (field === 'name') setNameTaken(null);
  }

  function leave(field: CameraFormField) {
    setTouched((current) => (current.has(field) ? current : new Set(current).add(field)));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const camera = await write(() => client.addCamera(cameraCreateBody(values)));
      toasts.success(`Added ${camera.name}.`);
      setValues(EMPTY_CAMERA_FORM);
      setTouched(new Set());
      setNameTaken(null);
      // The password input holds its own text: empty it too.
      if (passwordInput.current) passwordInput.current.value = '';
      onAdded(camera);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'camera_name_taken') {
        setNameTaken(caught.message);
        setTouched((current) => new Set(current).add('name'));
      } else {
        toasts.error(`Could not add the camera. ${errorMessage(caught)}`);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card card--padded stack cam-form" onSubmit={(event) => void submit(event)} noValidate>
      <TextField
        field="name"
        label="Camera name"
        required
        value={values.name}
        error={nameTaken ?? shown('name')}
        onChange={change}
        onBlur={leave}
      />
      <TextField
        field="ip"
        label="Camera IP address or host"
        required
        value={values.ip}
        error={shown('ip')}
        onChange={change}
        onBlur={leave}
      />
      <TextField
        field="username"
        label="Stream username"
        required
        value={values.username}
        error={shown('username')}
        onChange={change}
        onBlur={leave}
      />
      <TextField
        field="streamSecret"
        label="Stream password"
        required
        type="password"
        uncontrolled
        inputRef={passwordInput}
        value={values.streamSecret}
        error={shown('streamSecret')}
        onChange={change}
        onBlur={leave}
      />
      <TextField
        field="location"
        label="Location/Zone"
        value={values.location}
        error={shown('location')}
        onChange={change}
        onBlur={leave}
      />
      <TextField
        field="department"
        label="Department"
        value={values.department}
        error={shown('department')}
        onChange={change}
        onBlur={leave}
      />

      <div className="field">
        <span className="field__label">Stream address (the password stays hidden)</span>
        <code className="cam-form__rtsp">{maskedRtspUrlPreview(values.username, values.ip.trim())}</code>
      </div>

      <p id={costId} className="muted">
        {costNote(cameraCount)}
      </p>
      <label className="cam-form__check">
        <input
          type="checkbox"
          checked={values.acknowledgeCost}
          aria-describedby={costId}
          onChange={(event) => setValues((current) => ({ ...current, acknowledgeCost: event.target.checked }))}
        />
        I understand that searching footage uses my Meta credits
      </label>

      <div className="btn-row">
        <button type="submit" className="btn btn--primary" disabled={!canSubmit}>
          {submitting ? 'Adding…' : 'Add camera'}
        </button>
      </div>
    </form>
  );
}
