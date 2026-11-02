// The demo session: a UI-only flag. It is a convenience that lets the sign-in page lead into the app, NOT security.
// AskFootage has no accounts and no authentication, and the API does not check anything this flag says. Anyone can
// set it by hand in the browser console; nothing is protected by it.
//
// Stored in sessionStorage (gone when the tab closes). Every storage access is in try/catch: private modes and
// locked-down browsers throw, and then an in-memory flag keeps the page working for the life of the tab.
import { useSyncExternalStore } from 'react';

const KEY = 'askfootage.demoSession';

let memoryFlag = false;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function hasDemoSession(): boolean {
  try {
    return window.sessionStorage.getItem(KEY) === '1' || memoryFlag;
  } catch {
    return memoryFlag;
  }
}

export function startDemoSession(): void {
  memoryFlag = true;
  try {
    window.sessionStorage.setItem(KEY, '1');
  } catch {
    // Storage is unavailable: the in-memory flag above is the session.
  }
  notify();
}

export function clearDemoSession(): void {
  memoryFlag = false;
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Nothing stored, nothing to remove.
  }
  notify();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** True while a demo session exists; re-renders when it starts or ends. */
export function useDemoSession(): boolean {
  return useSyncExternalStore(subscribe, hasDemoSession, () => false);
}
