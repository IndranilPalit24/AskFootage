import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import type { DaySummary } from '../../api/generated/types';
import { Icon } from '../../components/Icon';
import { formatShortDay } from '../../lib/dates';

export const EXAMPLE_QUESTIONS = [
  'someone carrying a box',
  'anyone in the loading door',
  'someone waiting by the exit lane',
  'people carrying boxes through the loading door',
] as const;

/** The contract's limit for SearchRequest.question. */
export const QUESTION_MAX = 300;

interface AskBoxProps {
  /** The question to show first (the last one asked, when coming back to the results). */
  initialQuestion: string;
  /** Called with a question that is not blank. */
  onSubmit: (question: string) => void;
  days: DaySummary[];
  day: string;
  onDayChange: (day: string) => void;
  cameraName: string;
}

/**
 * The ask box: question, Search, example chips that fill the box, and the scope line (day and camera).
 * The draft question lives here, so typing re-renders only the box, never the result cards.
 */
export function AskBox({ initialQuestion, onSubmit, days, day, onDayChange, cameraName }: AskBoxProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [question, setQuestion] = useState(initialQuestion);
  const blank = question.trim().length === 0;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!blank) onSubmit(question.trim());
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter keeps the newline. Ignore Enter while an IME is composing text.
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (!blank) onSubmit(question.trim());
  }

  function fill(example: string) {
    setQuestion(example);
    textareaRef.current?.focus();
  }

  return (
    <div className="card ask">
      <form role="search" aria-label="Find Footage" onSubmit={handleSubmit}>
        <div className="ask__row">
          <label htmlFor="ask-question" className="visually-hidden">
            Ask about the footage
          </label>
          <textarea
            ref={textareaRef}
            id="ask-question"
            className="textarea ask__textarea"
            rows={3}
            maxLength={QUESTION_MAX}
            placeholder="Find your footage… e.g. someone carrying a box"
            aria-describedby="ask-keys"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button type="submit" className="btn btn--primary" disabled={blank}>
            <Icon name="search" />
            Search
          </button>
        </div>
        <p id="ask-keys" className="visually-hidden">
          Enter searches. Shift and Enter starts a new line.
        </p>
      </form>
      <ul className="examples" aria-label="Example questions">
        {EXAMPLE_QUESTIONS.map((example) => (
          <li key={example}>
            <button type="button" className="btn btn--sm" onClick={() => fill(example)}>
              {example}
            </button>
          </li>
        ))}
      </ul>
      <div className="scope">
        <span className="scope__item">
          <label htmlFor="ask-day">Day:</label>
          <select id="ask-day" className="select" value={day} onChange={(event) => onDayChange(event.target.value)}>
            {days.map((entry) => (
              <option key={entry.day} value={entry.day}>
                {formatShortDay(entry.day)}
              </option>
            ))}
          </select>
        </span>
        <span className="scope__item">Camera: {cameraName}</span>
      </div>
    </div>
  );
}
