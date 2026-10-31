// Smoke test: every route renders from the in-memory demo client, inside the shell.
import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from './ui-test-utils';

function expectShell() {
  expect(screen.getByRole('banner')).toBeTruthy();
  expect(screen.getByRole('navigation', { name: 'Main' })).toBeTruthy();
  expect(screen.getByRole('main')).toBeTruthy();
}

describe('every screen renders from the demo client', () => {
  it('Find Footage at /', async () => {
    renderApp('/');
    expect(screen.getByRole('heading', { level: 1, name: 'Find Footage' })).toBeTruthy();
    expect(await screen.findByLabelText('Ask about the footage')).toBeTruthy();
    expectShell();
  });

  it('Cameras at /cameras', async () => {
    renderApp('/cameras');
    expect(screen.getByRole('heading', { level: 1, name: 'Cameras' })).toBeTruthy();
    expect(await screen.findByRole('link', { name: 'Loading dock' })).toBeTruthy();
    expectShell();
  });

  it('Recordings at /cameras/:id/recordings', async () => {
    renderApp('/cameras/CAM-001/recordings');
    expect(await screen.findByRole('heading', { level: 1, name: 'Recordings' })).toBeTruthy();
    expect(await screen.findByText('4 recordings · 7 h · 2 ready')).toBeTruthy();
    expectShell();
  });

  it('Clip detail at /clip/:id', async () => {
    renderApp('/clip/clip-1029-104215');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Person carrying a box through the loading dock' }),
    ).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Why this matched' })).toBeTruthy();
    expectShell();
  });

  it('Zones at /zones', async () => {
    renderApp('/zones');
    expect(await screen.findByRole('heading', { level: 1, name: 'Zones' })).toBeTruthy();
    const list = await screen.findByRole('list', { name: 'Zones' });
    expect(within(list).getByText('Loading door')).toBeTruthy();
    expectShell();
  });

  it('Saved clips at /saved', async () => {
    renderApp('/saved');
    expect(screen.getByRole('heading', { level: 1, name: 'Saved clips' })).toBeTruthy();
    expect(await screen.findByText('No saved clips yet. Use Save clip on any result to keep it here.')).toBeTruthy();
    expectShell();
  });

  it('a calm page for an unknown address', async () => {
    renderApp('/nowhere');
    expect(await screen.findByRole('heading', { level: 1, name: 'Page not found' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Go to Find Footage' }).getAttribute('href')).toBe('/');
  });
});
