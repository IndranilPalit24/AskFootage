import { createContext, memo, use, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Icon } from '../components/Icon';

export type ToastTone = 'success' | 'error';

interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
}

export interface ToastActions {
  /** A confirmation (role="status"). */
  success: (message: string) => void;
  /** A failure (role="alert"). */
  error: (message: string) => void;
}

/** How long a toast stays, unless the pointer or keyboard focus is on it. */
export const TOAST_DURATION_MS = 4000;
/** Older toasts make way, so a burst of actions never fills the screen. */
const MAX_TOASTS = 3;

// The actions never change, so components that only raise toasts never re-render because of them.
const ToastActionsContext = createContext<ToastActions | null>(null);

interface ToastProps {
  toast: ToastItem;
  onDismiss: (id: number) => void;
}

const Toast = memo(function Toast({ toast, onDismiss }: ToastProps) {
  const [paused, setPaused] = useState(false);
  const { id, tone, message } = toast;

  useEffect(() => {
    if (paused) return undefined;
    const timer = window.setTimeout(() => onDismiss(id), TOAST_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [paused, id, onDismiss]);

  return (
    <div
      className={tone === 'error' ? 'toast toast--error' : 'toast toast--success'}
      data-testid="toast"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      {/* The message alone is the live region, so the close button is not read out with it. */}
      <p className="toast__message" role={tone === 'error' ? 'alert' : 'status'}>
        {message}
      </p>
      <button type="button" className="icon-btn toast__close" aria-label="Dismiss notification" onClick={() => onDismiss(id)}>
        <Icon name="close" size={16} />
      </button>
    </div>
  );
});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const lastId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((toast) => toast.id !== id));
  }, []);

  const actions = useMemo<ToastActions>(() => {
    function push(tone: ToastTone, message: string) {
      lastId.current += 1;
      const toast: ToastItem = { id: lastId.current, tone, message };
      setToasts((list) => [...list, toast].slice(-MAX_TOASTS));
    }
    return { success: (message) => push('success', message), error: (message) => push('error', message) };
  }, []);

  return (
    <ToastActionsContext value={actions}>
      {children}
      <div className="toasts">
        {toasts.map((toast) => (
          <Toast key={toast.id} toast={toast} onDismiss={dismiss} />
        ))}
      </div>
    </ToastActionsContext>
  );
}

export function useToasts(): ToastActions {
  const value = use(ToastActionsContext);
  if (!value) throw new Error('useToasts must be used inside ToastProvider');
  return value;
}
