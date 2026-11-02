import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ClipProof, SearchResponse } from '../../web/src/api/generated/types';
import { MockApiClient } from '../../web/src/api/mockClient';
import { renderApp, waitForBoot } from './ui-test-utils';

function proofFor(clipId: string): ClipProof {
  return {
    clipId,
    relation: 'carrying',
    startFrame: 10,
    endFrame: 70,
    startSeconds: 0.5,
    endSeconds: 3.5,
    trackIds: [1, 2],
    trackLabels: ['person', 'cardboard box'],
    measures: [
      { name: 'frames_together', value: 60 },
      { name: 'motion_agreement', value: 0.9123 },
    ],
    boxes: [],
  };
}

class ProofClient extends MockApiClient {
  constructor(private readonly withProof: boolean) {
    super();
  }
  override async search(request: Parameters<MockApiClient['search']>[0]): Promise<SearchResponse> {
    const response = await super.search(request);
    const first = response.clips[0];
    return { ...response, proofs: this.withProof && first ? [proofFor(first.id)] : [] };
  }
}

async function searchWith(client: MockApiClient) {
  renderApp('/', client);
  await waitForBoot();
  const box = await screen.findByLabelText<HTMLTextAreaElement>('Ask about the footage');
  fireEvent.change(box, { target: { value: 'someone carrying a box' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  return within(await screen.findByRole('list', { name: 'Results' })).findAllByRole('article');
}

describe('Why this matched proof', () => {
  it('shows relation, time range and measures on the clip that has a proof only', async () => {
    const cards = await searchWith(new ProofClient(true));
    expect(cards.length).toBeGreaterThan(0);
    const panel = within(cards[0]).getByRole('region', { name: 'Why this matched' });
    // Label and value rows, only from what the API returned.
    expect(panel.textContent).toContain('RelationCarrying');
    expect(panel.textContent).toContain('Seen in the recording0.5 s to 3.5 s');
    expect(panel.textContent).toContain('Frames together60');
    expect(panel.textContent).toContain('Motion agreement0.91');
    expect(panel.textContent).not.toMatch(/\/5|High/);
    for (const card of cards.slice(1)) expect(within(card).queryByText('Why this matched')).toBeNull();
  });

  it('is hidden when proofs is empty', async () => {
    await searchWith(new ProofClient(false));
    expect(screen.queryByText('Why this matched')).toBeNull();
  });
});
