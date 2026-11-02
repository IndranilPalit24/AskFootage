import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { ApiError } from '../../api/errors';
import { CODE_MESSAGES, SIGN_IN_COPY } from './copy';

const CODE_LENGTH = 6;

/** What to tell the person for a failed check. Nothing here includes the code. */
function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return CODE_MESSAGES.invalid;
    if (error.status === 429) return CODE_MESSAGES.tooMany;
    // A server started before the endpoint existed answers 404: say what to do instead of a vague failure.
    if (error.status === 404) return CODE_MESSAGES.outdatedApi;
  }
  return CODE_MESSAGES.failed;
}

/**
 * The 6-digit demo access code entry. A demo gate, not a login: the code is held only in this component's state,
 * is never stored or logged, and the field is emptied after a failed try.
 */
export function CodeEntry({
  check,
  onAccepted,
  onCancel,
}: {
  check: (code: string) => Promise<unknown>;
  onAccepted: () => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const errorId = useId();

  useEffect(() => input.current?.focus(), []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (code.length !== CODE_LENGTH) {
      setError(CODE_MESSAGES.incomplete);
      input.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await check(code);
      onAccepted();
    } catch (failure) {
      setCode('');
      setError(messageFor(failure));
      setBusy(false);
      input.current?.focus();
    }
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') onCancel();
  };

  return (
    <form className="signin__code" onSubmit={submit} onKeyDown={onKeyDown} noValidate>
      <label htmlFor="signin-code">{SIGN_IN_COPY.codeLabel}</label>
      <input
        ref={input}
        id="signin-code"
        className="signin__code-input"
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={CODE_LENGTH}
        spellCheck={false}
        value={code}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, CODE_LENGTH))}
      />
      <p className="signin__code-error" id={errorId} role="alert">
        {error}
      </p>
      <div className="signin__code-actions">
        <button type="submit" className="signin__btn signin__btn--primary" aria-busy={busy || undefined}>
          {SIGN_IN_COPY.codeSubmit}
        </button>
        <button type="button" className="signin__btn" onClick={onCancel}>
          {SIGN_IN_COPY.codeCancel}
        </button>
      </div>
    </form>
  );
}
