import { describe, expect, it } from 'vitest';

import html from '../../web/landing/index.html?raw';
const doc = new DOMParser().parseFromString(html, 'text/html');

describe('landing page', () => {
  it('has the semantic landmarks and one h1', () => {
    expect(doc.querySelector('header nav')).not.toBeNull();
    expect(doc.querySelectorAll('main')).toHaveLength(1);
    expect(doc.querySelector('footer')).not.toBeNull();
    expect(doc.querySelectorAll('h1')).toHaveLength(1);
    expect(doc.documentElement.lang).toBe('en');
  });

  it('has every required section and the demo link', () => {
    for (const id of ['how', 'proof', 'features', 'works', 'scenarios', 'privacy', 'cost']) {
      expect(doc.getElementById(id), id).not.toBeNull();
    }
    const demo = [...doc.querySelectorAll('a')].filter((a) => a.textContent?.trim() === 'Try the demo');
    expect(demo.length).toBeGreaterThanOrEqual(3);
    demo.forEach((a) => expect(a.getAttribute('href')).toBe('/'));
    expect(html).toContain('Illustrative examples, not customer testimonials.');
    expect(html).toContain('Every match shows its evidence.');
  });

  it('labels the ask input', () => {
    expect(doc.querySelector('label[for="q"]')).not.toBeNull();
  });

  it('has no external URLs and no brand or vendor names', () => {
    expect(html).not.toMatch(/https?:\/\//i);
    expect(doc.body.textContent + doc.title).not.toMatch(/openai|anthropic|claude|gemini|google|\bmeta\b|\bsam\b|yolo|gpt|nvidia|hikvision|dahua/i);
  });

  it('defines light and dark tokens', () => {
    expect(html).toContain('prefers-color-scheme:dark');
    expect(html).toContain('[data-theme="dark"]');
    for (const c of ['#0F1F3D', '#1D4ED8', '#F6F7F9', '#16181C', '#5B6170', '#E3E5E9']) expect(html).toContain(c);
  });
});
