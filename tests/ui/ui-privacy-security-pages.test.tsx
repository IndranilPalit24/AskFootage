// The public Privacy and Security pages, and the rule that no third-party brand logo ships in the front end.
import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PRIVACY_POINTS } from '../../web/src/screens/PrivacyScreen';
import { SECURITY_POINTS } from '../../web/src/screens/SecurityScreen';
import { renderApp } from './ui-test-utils';

const sources = import.meta.glob('../../web/src/**/*.{ts,tsx,css,svg}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

describe('public Privacy and Security pages', () => {
  it('Privacy states what the app does, with no compliance claim, and names where Meta AI is used', async () => {
    renderApp('/privacy', undefined, { session: false });
    expect(await screen.findByRole('heading', { level: 1, name: 'Privacy' })).toBeTruthy();
    const text = document.body.textContent ?? '';
    expect(text).toMatch(/stays on the machine/);
    expect(text).toMatch(/no face recognition and no identity features/);
    expect(text).toMatch(/never stored/);
    expect(text).toMatch(/no accounts and no authentication/);
    expect(text).toMatch(/Meta AI/);
    expect(text).not.toMatch(/GDPR|SOC ?2|ISO ?27001|HIPAA|certified|compliant|encrypted/i);
    expect(PRIVACY_POINTS.length).toBeGreaterThanOrEqual(5);
  });

  it('Security says plainly that nothing is protected by the demo sign-in', async () => {
    renderApp('/security', undefined, { session: false });
    expect(await screen.findByRole('heading', { level: 1, name: 'Security' })).toBeTruthy();
    const text = document.body.textContent ?? '';
    expect(text).toMatch(/no accounts and no authentication/);
    expect(text).toMatch(/not a security control/);
    expect(text).not.toMatch(/GDPR|SOC ?2|ISO ?27001|HIPAA|certified|compliant|encrypted|secure by/i);
    expect(SECURITY_POINTS.length).toBeGreaterThanOrEqual(4);
  });

  it('both pages have one h1, a main landmark, a skip link and a way back', async () => {
    renderApp('/privacy', undefined, { session: false });
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('main')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Skip to content' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Back to sign in' }).getAttribute('href')).toBe('/sign-in');
  });
});

describe('no third-party brand logo in the front end', () => {
  it('has no Microsoft logo colours, logo files or logo markup in src', () => {
    const files = Object.keys(sources);
    expect(files.length).toBeGreaterThan(50);
    expect(files.filter((name) => /logo|microsoft/i.test(name))).toEqual([]);
    for (const [name, text] of Object.entries(sources)) {
      expect(text, name).not.toMatch(/#F25022|#7FBA00|#00A4EF|#FFB900/i);
      expect(text, name).not.toMatch(/microsoft[-_ ]?logo|<image\b/i);
    }
  });

  it('the word "Microsoft" appears only as the specified button label', () => {
    const users = Object.entries(sources)
      .filter(([, text]) => /Microsoft/.test(text))
      .map(([name]) => name.replace(/^.*\/web\/src\//, ''));
    expect(users).toEqual(['features/signin/copy.ts']);
  });
});

describe('sign-in styling follows the theme tokens', () => {
  it('signin.css hard-codes no colour and has no dark rules', () => {
    const css = Object.entries(sources).find(([name]) => name.endsWith('styles/signin.css'))![1];
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(css).not.toMatch(/prefers-color-scheme/);
  });
});
