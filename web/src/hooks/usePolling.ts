import { useEffect, useEffectEvent } from 'react';

/**
 * Runs task every intervalMs while the page is visible. It pauses while document.hidden, runs once at once when
 * the page is visible again, stops on unmount, and never starts a run while the previous one is unfinished.
 * The task handles its own errors; anything that escapes is dropped so the timer keeps going.
 */
export function usePolling(task: () => Promise<void>, intervalMs: number): void {
  // The latest task is read when a run starts, so the timer is not rebuilt when the task changes.
  const run = useEffectEvent(task);

  useEffect(() => {
    let timer: number | undefined;
    let inFlight = false;
    let active = true;

    async function tick() {
      if (inFlight || !active) return;
      inFlight = true;
      try {
        await run();
      } catch {
        // Reported by the task itself; the next tick tries again.
      } finally {
        inFlight = false;
      }
    }

    function start() {
      if (timer === undefined) timer = window.setInterval(() => void tick(), intervalMs);
    }

    function stop() {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
    }

    function onVisibilityChange() {
      if (document.hidden) {
        stop();
      } else {
        void tick();
        start();
      }
    }

    if (!document.hidden) start();
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      active = false;
      stop();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [intervalMs]);
}
