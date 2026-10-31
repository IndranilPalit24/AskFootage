// Layout contract of the Find Footage start screen. jsdom does no layout, but it does run the cascade: the
// real global.css is loaded into the document, so these tests read the styles the browser would apply.
import { fireEvent, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import globalCss from '../../web/src/styles/global.css?raw';
import { renderApp, waitForBoot } from './ui-test-utils';

let sheet: HTMLStyleElement;

beforeEach(() => {
  sheet = document.createElement('style');
  sheet.textContent = globalCss;
  document.head.append(sheet);
});

afterEach(() => {
  sheet.remove();
});

async function openStartScreen() {
  renderApp('/');
  await waitForBoot();
  const box = await screen.findByLabelText<HTMLTextAreaElement>('Ask about the footage');
  return { box, find: screen.getByTestId('find-footage') };
}

/** The declarations of the rule whose selector is exactly `selector` (top level of the file). */
function ruleBody(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = globalCss.match(new RegExp(`(?:^|\\n)${escaped} \\{([^}]*)\\}`));
  return match ? match[1] : '';
}

describe('Find Footage start screen layout', () => {
  it('before the first search, the heading, ask box, examples and Day selector are one centred group', async () => {
    const { find } = await openStartScreen();
    expect([...find.classList]).toEqual(['find', 'find--start']);

    const [group, ...rest] = [...find.children] as HTMLElement[];
    expect(group.className).toBe('find__group');
    expect(within(group).getByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
    expect(within(group).getByText('Ask a question about your footage. Each result shows the proof.')).toBeTruthy();
    expect(within(group).getByTestId('ask-box')).toBeTruthy();
    expect(within(group).getByRole('list', { name: 'Example questions' })).toBeTruthy();
    expect(within(group).getByLabelText('Day:')).toBeTruthy();

    // Besides the group, only the empty live region, which takes no space: nothing else to centre, and
    // nothing sits at the bottom of the page.
    expect(rest.map((element) => element.className)).toEqual(['results-status']);
    expect(rest[0].textContent).toBe('');
    expect(getComputedStyle(rest[0]).marginTop).toBe('0px');
    expect(getComputedStyle(rest[0]).marginBottom).toBe('0px');
    expect(find.nextElementSibling).toBeNull();

    // Centred on both axes.
    const style = getComputedStyle(find);
    expect(style.display).toBe('flex');
    expect(style.flexDirection).toBe('column');
    expect(style.justifyContent).toBe('center');
    expect(style.flexGrow).toBe('1');
    expect(getComputedStyle(group).textAlign).toBe('center');

    // The column fills the space under the topbar, so "centre" means the middle of the visible page.
    const main = screen.getByRole('main');
    expect(getComputedStyle(main).display).toBe('flex');
    expect(getComputedStyle(main).flexDirection).toBe('column');
    expect(getComputedStyle(main).minHeight).toBe('calc(100dvh - var(--topbar-height))');
    // Equal space above and below, so the middle of the column is the middle of the visible page.
    expect(getComputedStyle(main).paddingTop).toBe(getComputedStyle(main).paddingBottom);
    expect(getComputedStyle(main).paddingTop).toBe('var(--space-6)');
    const inner = find.parentElement!;
    expect(inner.className).toBe('main__inner');
    expect(getComputedStyle(inner).display).toBe('flex');
    expect(getComputedStyle(inner).flexGrow).toBe('1');
  });

  it('the stylesheet holds the centring rule for .find--start', () => {
    const start = ruleBody('.find--start');
    expect(start).toMatch(/display: flex;/);
    expect(start).toMatch(/flex-direction: column;/);
    expect(start).toMatch(/justify-content: center;/);
  });

  it('the Search icon button sits inside the ask box, after the question, at the bottom-right', async () => {
    const { box } = await openStartScreen();
    const askBox = screen.getByTestId('ask-box');
    const button = screen.getByRole('button', { name: 'Search' });

    expect(button.getAttribute('aria-label')).toBe('Search');
    expect(button.getAttribute('type')).toBe('submit');
    expect(button.textContent).toBe('');
    expect(button.querySelector('svg')).toBeTruthy();

    const actions = button.parentElement!;
    expect(actions.className).toBe('ask__actions');
    expect(actions.parentElement).toBe(askBox);
    expect(askBox.lastElementChild).toBe(actions);
    expect(box.compareDocumentPosition(actions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // A bordered box with 12px corners; the button row is inside it, in the flow, pushed to the right.
    const boxStyle = getComputedStyle(askBox);
    expect(boxStyle.borderRadius).toBe('12px');
    expect(boxStyle.display).toBe('flex');
    expect(boxStyle.flexDirection).toBe('column');
    const actionsStyle = getComputedStyle(actions);
    expect(actionsStyle.display).toBe('flex');
    expect(actionsStyle.justifyContent).toBe('flex-end');
    expect(['absolute', 'fixed']).not.toContain(actionsStyle.position);
    expect(['absolute', 'fixed']).not.toContain(getComputedStyle(button).position);
  });

  it('nothing forces a horizontal scroll on a phone: long example chips wrap', async () => {
    await openStartScreen();
    const chip = screen.getByRole('button', { name: 'people carrying boxes through the loading door' });
    expect(getComputedStyle(chip).whiteSpace).toBe('normal');
    expect(getComputedStyle(screen.getByTestId('ask-box')).minWidth).toBe('0px');
    expect(getComputedStyle(screen.getByLabelText('Ask about the footage')).width).toBe('100%');
  });

  it('after a search the group moves to the top and the results follow it', async () => {
    const { box, find } = await openStartScreen();
    fireEvent.change(box, { target: { value: 'someone carrying a box' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    // Switched as soon as the search starts, not when the answer arrives.
    expect([...find.classList]).toEqual(['find']);
    expect(getComputedStyle(find).justifyContent).not.toBe('center');
    expect(getComputedStyle(screen.getByRole('main')).display).not.toBe('flex');

    expect(await screen.findByText('1 clip')).toBeTruthy();
    expect([...find.classList]).toEqual(['find']);
    expect([...find.children].map((element) => element.className)).toEqual([
      'find__group',
      'results-status',
      'clip-list',
    ]);
    expect(getComputedStyle(find.firstElementChild!).textAlign).not.toBe('center');
  });
});
