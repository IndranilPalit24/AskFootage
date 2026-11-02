// The Minimalism & Swiss Style contract: contrast of the main colour pairs (computed, WCAG 2.x), the
// responsive rules, left-aligned text, and the interaction states being defined once.
import { describe, expect, it } from 'vitest';
import globalCss from '../../web/src/styles/global.css?raw';
import { tokens } from '../../web/src/styles/tokens';

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((index) => {
    const value = parseInt(hex.slice(index, index + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

/** WCAG contrast ratio of two #RRGGBB colours. */
function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

const { color } = tokens;

describe('contrast (light theme, the only theme)', () => {
  const textPairs: Array<[string, string, string]> = [
    ['text on page', color.text, color.page],
    ['muted text on page', color.textMuted, color.page],
    ['muted text on hover fill', color.textMuted, color.hoverFill],
    ['text on hover fill', color.text, color.hoverFill],
    ['text on pressed fill', color.text, color.activeFill],
    ['accent text on page', color.accent, color.page],
    ['accent text on hover fill', color.accent, color.hoverFill],
    ['accent text on pressed fill', color.accent, color.activeFill],
    ['text on accent button', color.onAccent, color.accent],
    ['text on accent button, hover', color.onAccent, color.accentHover],
    ['error text on page', color.danger, color.page],
    // Welcome page (trust colours).
    ['white text on navy', color.onNavy, color.navy],
    ['muted text on navy', color.onNavyMuted, color.navy],
    ['navy heading on page', color.navy, color.page],
    ['navy heading on surface', color.navy, color.surface],
    ['text on surface', color.text, color.surface],
    ['muted text on surface', color.textMuted, color.surface],
    ['accent text on surface', color.accent, color.surface],
    ['white label on the evidence box fill', color.onNavy, color.evidenceBox],
  ];
  it.each(textPairs)('%s is at least 4.5:1', (_name, foreground, background) => {
    expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
  });

  const graphicPairs: Array<[string, string, string]> = [
    ['field border on page', color.fieldBorder, color.page],
    ['focus ring on page', color.accent, color.page],
    ['online dot on page', color.statusOnline, color.page],
    ['offline dot on page', color.statusOffline, color.page],
    ['focus ring on navy (white)', color.onNavy, color.navy],
    ['evidence box outline on the frame placeholder', color.evidenceBox, color.hoverFill],
  ];

  it('the accent is not used on navy: it is only 2.4:1 there, so navy bands use white', () => {
    expect(contrast(color.accent, color.navy)).toBeLessThan(3);
    expect(globalCss).toMatch(/\.welcome-band :focus-visible \{\s*outline-color: var\(--color-on-navy\);/);
  });
  it.each(graphicPairs)('%s is at least 3:1', (_name, foreground, background) => {
    expect(contrast(foreground, background)).toBeGreaterThanOrEqual(3);
  });

  it('the standby dot (the specified #CA8A04) is 2.9:1, just under 3:1: it is never alone, a text label always says the status', () => {
    expect(contrast(color.statusStandby, color.page)).toBeGreaterThanOrEqual(2.9);
  });

  it('the hairline is decoration only: the dots always have a text label, so no 3:1 is asked of it', () => {
    expect(contrast(color.border, color.page)).toBeLessThan(3);
  });
});

describe('Swiss style rules in the stylesheet', () => {
  it('text is left-aligned: nothing is centred', () => {
    expect(globalCss).not.toMatch(/text-align:\s*center/);
  });

  it('only the five type sizes and two weights are used', () => {
    const sizes = new Set([...globalCss.matchAll(/font-size:\s*var\(--font-size-(\w+)\)/g)].map((match) => match[1]));
    // base is the 14px body size; 32 is the welcome page's headline, used once.
    expect([...sizes].sort()).toEqual(['12', '14', '16', '24', '32', 'base']);
    expect(globalCss.match(/font-size:\s*var\(--font-size-32\)/g)).toHaveLength(1);
    const weights = new Set([...globalCss.matchAll(/font-weight:\s*var\(--font-weight-(\w+)\)/g)].map((match) => match[1]));
    expect([...weights].sort()).toEqual(['regular', 'semibold']);
  });

  it('the content column is 840px wide at most and small screens get the 16px gutter', () => {
    expect(globalCss).toMatch(/\.main__inner \{[^}]*max-width: var\(--content-max-width\);/);
    const narrow = globalCss.slice(globalCss.indexOf('@media (max-width: 640px)'));
    expect(narrow).toMatch(/\.main \{[^}]*padding: var\(--space-5\) var\(--gutter\) var\(--space-6\);/);
    // The main column can shrink, so it never forces a sideways scroll; wide tables scroll inside their wrapper.
    expect(globalCss).toMatch(/\.main \{[^}]*min-width: 0;/);
    expect(globalCss).toMatch(/\.table-wrap \{[^}]*overflow-x: auto;/);
    // Result cards stack on a phone.
    expect(narrow).toMatch(/\.clip-card,\s*\n\s*\.saved-row \{\s*flex-direction: column;/);
    // 16px fields on a phone, so it does not zoom in.
    expect(narrow).toMatch(/\.textarea \{\s*font-size: var\(--font-size-16\);/);
  });

  it('status colours are used only by the 8px camera dots', () => {
    const used = [...globalCss.matchAll(/var\(--color-status-(online|standby|offline)\)/g)];
    expect(used).toHaveLength(3);
    for (const name of ['online', 'standby', 'offline']) {
      expect(globalCss).toMatch(new RegExp(`\\.cam-dot--${name} \\{\\s*background: var\\(--color-status-${name}\\);`));
    }
    expect(globalCss).toMatch(/\.cam-dot \{[^}]*width: var\(--status-dot\);[^}]*height: var\(--status-dot\);/);
  });

  it('interaction states are defined once, for hover, active, focus-visible, disabled and loading', () => {
    expect(globalCss).toMatch(/:focus-visible \{\s*outline: var\(--focus-ring-width\) solid var\(--color-accent\);\s*outline-offset: var\(--focus-ring-offset\);/);
    expect(tokens.focusRing).toEqual({ width: '2px', offset: '2px' });
    expect(globalCss).toMatch(/\.btn:hover,[^{]*\{\s*background: var\(--color-hover-fill\);/);
    expect(globalCss).toMatch(/\.btn:active,[^{]*\{\s*background: var\(--color-active-fill\);/);
    expect(globalCss).toMatch(/\.btn\[aria-disabled='true'\],[^{]*\{\s*cursor: not-allowed;\s*opacity: var\(--opacity-disabled\);/);
    expect(globalCss).toMatch(/\.btn\[aria-busy='true'\] \{\s*cursor: progress;/);
    // The ring is never switched off for a control, except the textarea inside the ask box, which shows it on the box.
    const removals = [...globalCss.matchAll(/([^{}\n]+:focus-visible)\s*\{\s*outline:\s*none/g)].map((match) => match[1].trim());
    expect(removals).toEqual(['.ask__textarea:focus-visible']);
    expect(globalCss).toMatch(/\.ask__box:focus-within \{[^}]*outline: var\(--focus-ring-width\) solid var\(--color-accent\);/);
  });

  it('motion is short and switched off for people who ask for less', () => {
    expect(tokens.motion.fast).toBe('150ms');
    expect(globalCss).toMatch(/prefers-reduced-motion: reduce\) \{\s*\*,\s*\*::before,\s*\*::after \{\s*transition: none !important;/);
  });

  it('no shadows, gradients or pill shapes', () => {
    const rules = globalCss.replace(/\/\*[\s\S]*?\*\//g, '');
    expect(rules).not.toMatch(/box-shadow|text-shadow|gradient|radius-pill|999px/);
  });
});
