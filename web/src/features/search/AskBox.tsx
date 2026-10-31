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
}

/**
 * The ask box (question with the Search button inside it, bottom-right), example chips that fill the box,
 * and the Day selector. Searches cover every camera. The draft question lives here, so typing re-renders
 * only the box, never the result cards.
 */
export function AskBox({ initialQuestion, onSubmit, days, day, onDayChange }: AskBoxProps) {
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
    <div className="ask">
      <form role="search" aria-label="Find Footage" onSubmit={handleSubmit}>
        <div className="ask__box" data-testid="ask-box">
          <label htmlFor="ask-question" className="visually-hidden">
            Ask about the footage
          </label>
          <textarea
            ref={textareaRef}
            id="ask-question"
            className="ask__textarea"
            rows={3}
            maxLength={QUESTION_MAX}
            placeholder="Find your footage… e.g. someone carrying a box"
            aria-describedby="ask-keys"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={handleKeyDown}
          />
          <div className="ask__actions">
            <button type="submit" className="btn btn--primary ask__submit" aria-label="Search" disabled={blank}>
              <Icon name="search" />
            </button>
          </div>
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
        <label htmlFor="ask-day">Day:</label>
        <select id="ask-day" className="select" value={day} onChange={(event) => onDayChange(event.target.value)}>
          {days.map((entry) => (
            <option key={entry.day} value={entry.day}>
              {formatShortDay(entry.day)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
