// Shared helpers for the UI tests. Every test gets a fresh in-memory demo client: no network, ever.
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ApiClient } from '../../web/src/api/client';
import { MockApiClient } from '../../web/src/api/mockClient';
import { App } from '../../web/src/app/App';

export function renderApp(path = '/', client: ApiClient = new MockApiClient()) {
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <App client={client} />
    </MemoryRouter>,
  );
  return { ...view, client };
}

/** Waits until the shell has loaded the status and days: the topbar shows the selected day ("Fri 30 Oct"). */
export async function waitForBoot(day = 'Fri 30 Oct'): Promise<void> {
  await within(screen.getByRole('banner')).findByText(day);
}

/** A promise with its resolve/reject handles, to hold an API answer back while a test looks at the loading state. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  // A test may reject before the screen has asked for the promise (effects run after the first paint), and
  // Node would call that an unhandled rejection. This marks it handled; whoever awaits it still gets the rejection.
  promise.catch(() => undefined);
  return { promise, resolve, reject };
}

/** Pretends an element has a laid-out size (jsdom does no layout). */
export function giveSize(element: Element, width: number, height: number): void {
  element.getBoundingClientRect = () =>
    ({ x: 0, y: 0, left: 0, top: 0, width, height, right: width, bottom: height, toJSON: () => ({}) }) as DOMRect;
}
