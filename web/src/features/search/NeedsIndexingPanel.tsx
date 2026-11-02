import { useEffect, useEffectEvent, useId, useRef, useState } from 'react';
import { useApiClient } from '../../app/ApiContext';
import { ApiError, errorMessage } from '../../api/errors';
import type { ConceptState, NeedsIndexing } from '../../api/generated/types';

/** How often a running search is looked at, in milliseconds. */
export const CONCEPT_POLL_MS = 2000;

interface NeedsIndexingPanelProps {
  item: NeedsIndexing;
  /** The day that was searched; the search for the new object covers the same day. */
  day: string;
  /** Called once when the search for the object is done, so the results can be asked for again. */
  onDone: () => void;
}

export function formatDollars(amount: number): string {
  if (amount > 0 && amount < 0.01) return 'less than $0.01';
  return `$${amount.toFixed(2)}`;
}

/** A plain sentence for the failures the person can do nothing about by trying again. */
function plainMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === 'budget_exceeded') {
    return 'This search would go over the spending limit, so it was not started. Nothing was spent.';
  }
  if (error instanceof ApiError && error.code === 'indexing_not_configured') {
    return 'Searching for new objects is not set up in this build, so nothing was started.';
  }
  return errorMessage(error);
}

const STATE_TEXT: Record<ConceptState, string> = {
  queued: 'Waiting to start…',
  running: 'Searching the footage…',
  done: 'Done. Updating the results…',
  failed: 'The search did not finish.',
};

/** One calm panel for one object the question names that the footage has not been searched for yet. */
export function NeedsIndexingPanel({ item, day, onDone }: NeedsIndexingPanelProps) {
  const client = useApiClient();
  const checkboxId = useId();
  const [confirmed, setConfirmed] = useState(false);
  const [starting, setStarting] = useState(false);
  // The state of the pass: from the search answer at first, then from each answer of the API.
  const [state, setState] = useState<ConceptState | null>(item.state === 'not_indexed' ? null : item.state);
  const [failure, setFailure] = useState<string | null>(null);
  const [failedMessage, setFailedMessage] = useState<string | null>(null);
  const finished = useRef(false);

  const active = state === 'queued' || state === 'running';

  const finish = useEffectEvent(onDone);

  useEffect(() => {
    if (state === 'done' && !finished.current) {
      finished.current = true;
      finish();
    }
  }, [state]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let inFlight = false;
    const timer = window.setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      client.getConcept(item.noun).then(
        (job) => {
          inFlight = false;
          if (cancelled) return;
          setState(job.state);
          if (job.state === 'failed') setFailedMessage(job.message ?? 'The search did not finish. Try again.');
        },
        (error: unknown) => {
          inFlight = false;
          if (cancelled) return;
          setState(null);
          setFailure(plainMessage(error));
        },
      );
    }, CONCEPT_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [active, client, item.noun]);

  function start() {
    if (!confirmed || starting) return;
    setStarting(true);
    setFailure(null);
    setFailedMessage(null);
    client.requestConcept({ noun: item.noun, confirm: true, day }).then(
      (job) => {
        setStarting(false);
        setState(job.state);
        if (job.state === 'failed') setFailedMessage(job.message ?? 'The search did not finish. Try again.');
      },
      (error: unknown) => {
        setStarting(false);
        setState(null);
        setFailure(plainMessage(error));
      },
    );
  }

  // The cost was accepted for this panel already; a failed pass is asked for again with the same answer.
  function retry() {
    if (confirmed) start();
    else setState(null);
  }

  const failed = state === 'failed';
  const showForm = !active && state !== 'done' && !failed;
  const heading = `Not searched yet for ${item.noun}`;

  return (
    <section className="card card--padded needs-indexing" aria-label={heading}>
      <h2 className="needs-indexing__title">{heading}</h2>
      <p className="muted">
        Searching {item.recordingIds.length === 1 ? '1 recording' : `${item.recordingIds.length} recordings`} for {item.noun} is
        estimated to cost <strong className="num">{formatDollars(item.estimatedCostUsd)}</strong>. It runs once, and only after you
        confirm.
      </p>
      {showForm ? (
        <div className="needs-indexing__form">
          <label className="needs-indexing__confirm" htmlFor={checkboxId}>
            <input id={checkboxId} type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
            I accept this cost
          </label>
          <button
            type="button"
            className="btn btn--primary btn--sm"
            disabled={!confirmed || starting}
            onClick={start}
          >
            Search for {item.noun}
          </button>
        </div>
      ) : null}
      <div className="needs-indexing__status" aria-live="polite">
        {starting ? <p className="muted">Starting the search…</p> : null}
        {state ? <p className={failed ? 'error-text' : 'muted'}>{STATE_TEXT[state]}</p> : null}
        {failed && failedMessage ? <p className="error-text">{failedMessage}</p> : null}
        {failure ? <p className="error-text">{failure}</p> : null}
      </div>
      {failed ? (
        <p className="needs-indexing__action">
          <button type="button" className="btn btn--sm" disabled={starting} onClick={retry}>
            Try again
          </button>
        </p>
      ) : null}
    </section>
  );
}
