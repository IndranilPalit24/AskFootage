import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react';

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])';

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** The buttons; the one marked data-autofocus (else the first) gets focus when the dialog opens. */
  actions: ReactNode;
}

/**
 * A confirmation dialog: focus moves in when it opens, Tab stays inside, Escape closes it, and focus goes back to
 * what had it before (or to the page's main area when that element is gone, for example a deleted row's button).
 */
export function Modal({ title, onClose, children, actions }: ModalProps) {
  const titleId = useId();
  const bodyId = useId();
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const first = dialog.current?.querySelector<HTMLElement>('[data-autofocus]') ?? dialog.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    return () => {
      if (opener && opener !== document.body && opener.isConnected) opener.focus();
      else document.querySelector<HTMLElement>('main')?.focus();
    };
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab' || !dialog.current) return;
    const items = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (items.length === 0) return;
    const firstItem = items[0];
    const lastItem = items[items.length - 1];
    if (event.shiftKey && document.activeElement === firstItem) {
      event.preventDefault();
      lastItem.focus();
    } else if (!event.shiftKey && document.activeElement === lastItem) {
      event.preventDefault();
      firstItem.focus();
    }
  }

  return (
    <div className="modal-backdrop">
      <div
        ref={dialog}
        className="modal card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        onKeyDown={handleKeyDown}
      >
        <h2 id={titleId}>{title}</h2>
        <div id={bodyId} className="modal__body">
          {children}
        </div>
        <div className="btn-row modal__actions">{actions}</div>
      </div>
    </div>
  );
}
