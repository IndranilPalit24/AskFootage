// The welcome page's sections below the hero: pipeline, proof preview, features, sources, scenarios,
// privacy, cost, the closing band and footer; plus the dark tokens and the brand/model-name check.
import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import globalCss from '../../web/src/styles/global.css?raw';
import { costExample, formatCents } from '../../web/src/features/welcome/content';
import { tokensCss, tokens } from '../../web/src/styles/tokens';
import { renderApp } from './ui-test-utils';

function section(name: string): HTMLElement {
  return screen.getByRole('region', { name });
}

describe('welcome page: how it works', () => {
  it('shows add, index, ask as three steps with a sample mock each', () => {
    renderApp('/welcome');
    const how = section('How it works');
    const steps = how.querySelectorAll('ol > li');
    const stepHeadings = within(how).getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(stepHeadings).toEqual(['Add footage', 'Index once', 'Ask anything']);
    expect(steps).toHaveLength(3);
    expect(within(how).getAllByText('Sample content')).toHaveLength(3);
  });
});

describe('welcome page: proof preview', () => {
  it('draws the frame, the red box, the 0:01-0:05 interval and the facts, marked as sample', () => {
    renderApp('/welcome');
    const proof = section('Every clip comes with its proof');
    const frame = within(proof).getByRole('img', { name: /Sample frame/ });
    expect(frame.querySelector('.proof-svg__box')).not.toBeNull();
    expect(within(proof).getByText(/Matched interval 0:01-0:05/)).toBeTruthy();
    const interval = proof.querySelector<HTMLElement>('.welcome-proof__interval')!;
    expect(interval.style.left).toBe('10%');
    expect(interval.style.width).toBe('40%');
    const why = within(proof).getByRole('heading', { level: 3, name: 'Why this matched' }).parentElement!;
    for (const term of ['Relation', 'Time range', 'Object', 'Confidence']) expect(within(why).getByText(term)).toBeTruthy();
    expect(within(why).getByText('0:01-0:05')).toBeTruthy();
    expect(within(why).getByText('Sample content')).toBeTruthy();
  });

  it('the evidence box is red and the page shows no face or identity feature', () => {
    expect(tokens.color.evidenceBox).toBe('#DC2626');
    expect(globalCss).toMatch(/\.proof-svg__box \{[^}]*stroke: var\(--color-evidence-box\)/);
    renderApp('/welcome');
    expect(document.body.textContent).not.toMatch(/face (match|detect|id)|identif(y|ied) (a )?person|recogni[sz]e (a )?(person|face)/i);
  });
});

describe('welcome page: features, sources and scenarios', () => {
  it('has the six feature cards', () => {
    renderApp('/welcome');
    const titles = within(section('Features')).getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual([
      'Plain-English search',
      'Proof with every clip',
      'Daily footage library per camera',
      'Zones',
      'Saved clips',
      'Any object you can name',
    ]);
  });

  it('has three generic source tiles and no brand names', () => {
    renderApp('/welcome');
    const titles = within(section('Works with the footage you already have')).getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual(['IP cameras via RTSP', 'MP4 and MOV uploads', 'Daily recording folders']);
  });

  it('has three illustrative scenarios and the not-testimonials note, with no invented people or figures', () => {
    renderApp('/welcome');
    const scenarios = section('Example scenarios');
    const titles = within(scenarios).getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual(['Warehouse loading dock', 'Retail shop floor', 'Office entrance']);
    expect(within(scenarios).getByText('Illustrative examples, not customer testimonials.')).toBeTruthy();
    expect(scenarios.textContent).not.toMatch(/\d+%|"[^"]+" -|testimonial:/i);
  });
});

describe('welcome page: privacy', () => {
  it('says no face recognition, no identity features, and that the camera password is never stored', () => {
    renderApp('/welcome');
    const privacy = section('No face recognition. No identity features.');
    expect(within(privacy).getByText(/never stored/)).toBeTruthy();
    expect(within(privacy).getByText(/never works out who someone is/)).toBeTruthy();
  });
});

describe('welcome page: cost', () => {
  it('states the price, that search is free, and a worked example whose arithmetic is right', () => {
    renderApp('/welcome');
    const cost = section('Cost');
    expect(within(cost).getByText(/About \$0\.20 per 1,000 frames, for each object type, to index\. Searching afterwards is free\./)).toBeTruthy();
    // 30 min x 60 s x 5 fps = 9,000 frames; 9,000 / 1,000 x $0.20 = $1.80; x 4 object types = $7.20.
    const example = costExample();
    expect(example.frames).toBe(9000);
    expect(formatCents(example.centsPerObjectType)).toBe('$1.80');
    expect(formatCents(example.totalCents)).toBe('$7.20');
    expect(within(cost).getByText('30 x 60 s x 5 fps = 9,000')).toBeTruthy();
    expect(within(cost).getByText('9,000 / 1,000 x $0.20 = $1.80')).toBeTruthy();
    expect(within(cost).getByText('4 x $1.80 = $7.20')).toBeTruthy();
    // 50 frames at 5 fps = 10 s; 50 / 1,000 x $0.20 = $0.01.
    expect(within(cost).getByText(/at least 50 frames \(10 seconds at 5 fps\).*at least \$0\.01/)).toBeTruthy();
  });
});

describe('welcome page: closing band and footer', () => {
  it('ends with the call to action, a demo link, and a footer', () => {
    renderApp('/welcome');
    const closing = section('See it find a moment in your footage');
    expect(within(closing).getByRole('link', { name: 'Try the demo' }).getAttribute('href')).toBe('/');
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByRole('navigation', { name: 'Footer' })).toBeTruthy();
  });

  it('every "Try the demo" link goes to Find Footage', () => {
    renderApp('/welcome');
    const links = screen.getAllByRole('link', { name: 'Try the demo' });
    expect(links.length).toBeGreaterThanOrEqual(3);
    for (const link of links) expect(link.getAttribute('href')).toBe('/');
  });
});

describe('welcome page: names, headings and images', () => {
  it('has no model, vendor or brand name anywhere in the text, labels or alt text', () => {
    renderApp('/welcome');
    const text = [
      document.body.textContent,
      ...[...document.querySelectorAll('[aria-label],[alt],[title]')].map(
        (el) => `${el.getAttribute('aria-label')} ${el.getAttribute('alt')} ${el.getAttribute('title')}`,
      ),
    ].join(' ');
    expect(text).not.toMatch(/\b(sam|muse|meta|llama|openai|anthropic|claude|gemini|gpt|google|nvidia|yolo|hikvision|dahua|axis|ubiquiti)\b/i);
  });

  it('has one h1 and no skipped heading levels, no raster images, and every section is a labelled region', () => {
    renderApp('/welcome');
    const levels = screen.getAllByRole('heading').map((h) => Number(h.tagName.slice(1)));
    expect(levels.filter((l) => l === 1)).toHaveLength(1);
    levels.forEach((level, index) => {
      if (index > 0) expect(level - levels[index - 1]).toBeLessThanOrEqual(1);
    });
    expect(document.querySelectorAll('img')).toHaveLength(0);
    const regions = screen.getAllByRole('region').map((r) => r.getAttribute('id'));
    expect(regions).toEqual(expect.arrayContaining(['how', 'proof', 'features', 'sources', 'scenarios', 'privacy', 'cost']));
  });

  it('every in-page link in the top bar points at a section that exists', () => {
    renderApp('/welcome');
    const nav = within(screen.getByRole('banner')).getByRole('navigation', { name: 'Page sections' });
    for (const link of within(nav).getAllByRole('link')) {
      const id = link.getAttribute('href')!.slice(1);
      expect(document.getElementById(id), id).not.toBeNull();
    }
  });

  it('status colours appear only on 8px dots that sit beside a text label', () => {
    renderApp('/welcome');
    const dots = document.querySelectorAll('.cam-dot--online');
    expect(dots.length).toBeGreaterThan(0);
    dots.forEach((dot) => {
      expect(dot.classList.contains("cam-dot")).toBe(true);
      expect(dot.parentElement!.textContent!.trim().length).toBeGreaterThan(0);
    });
    expect(tokens.size.statusDot).toBe('8px');
  });
});

describe('one light theme', () => {
  it('publishes no dark palette: no prefers-color-scheme block in the tokens', () => {
    expect(tokensCss()).not.toContain('prefers-color-scheme');
    expect(tokensCss()).not.toContain('@media');
  });

  it('the stylesheet has a reduced-motion rule and a 16px gutter token', () => {
    expect(globalCss).toContain('prefers-reduced-motion: reduce');
    expect(globalCss).toContain('prefers-reduced-motion: no-preference');
    expect(tokens.size.gutter).toBe('16px');
  });
});
