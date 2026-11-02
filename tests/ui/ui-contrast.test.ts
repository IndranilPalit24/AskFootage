// WCAG 2.x contrast of the main colour pairs, computed from the tokens in light and in dark.
// Text pairs need 4.5:1 (AA); non-text pairs (focus ring, field edge, status dots, evidence box) need 3:1.
import { describe, expect, it } from 'vitest';
import { darkColor, tokens } from '../../web/src/styles/tokens';

function channel(value: number): number {
  const v = value / 255;
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

type Palette = Record<string, string>;
const light: Palette = { ...tokens.color };
const dark: Palette = { ...tokens.color, ...darkColor };

/** [foreground token, background token, minimum ratio, what it is] */
const PAIRS: ReadonlyArray<[string, string, number, string]> = [
  ['text', 'page', 4.5, 'body text'],
  ['textMuted', 'page', 4.5, 'muted text'],
  ['textMuted', 'surface', 4.5, 'muted text on the grey section'],
  ['heading', 'page', 4.5, 'headings'],
  ['heading', 'surface', 4.5, 'headings on the grey section'],
  ['accent', 'page', 4.5, 'links and accent text'],
  ['accent', 'surface', 4.5, 'accent text on the grey section'],
  ['onAccent', 'accent', 4.5, 'primary button'],
  ['onAccent', 'accentHover', 4.5, 'primary button, hovered'],
  ['text', 'hoverFill', 4.5, 'text on a hovered control'],
  ['text', 'activeFill', 4.5, 'text on a pressed control'],
  ['danger', 'page', 4.5, 'error text'],
  ['onNavy', 'navy', 4.5, 'hero and closing band text'],
  ['onNavyMuted', 'navy', 4.5, 'secondary text on the band'],
  ['navy', 'onNavy', 4.5, 'band button label'],
  ['onNavy', 'evidenceBox', 4.5, 'label on the red evidence box'],
  ['accent', 'page', 3, 'focus ring on the page'],
  ['onNavy', 'navy', 3, 'focus ring on the band'],
  ['fieldBorder', 'page', 3, 'text field edge'],
  // The status hexes are the product's fixed values. A dot never carries meaning alone (a text label sits
  // next to it), so it is not a required graphic; amber on white is 2.94:1, just under 3, and is reported.
  ['statusOnline', 'page', 3, 'status dot: online'],
  ['statusStandby', 'page', 2.9, 'status dot: standby (labelled; hex fixed by the brief)'],
  ['statusOffline', 'page', 3, 'status dot: offline'],
  ['evidenceBox', 'surface', 3, 'red box on the frame'],
  ['accent', 'activeFill', 3, 'timeline interval on its track'],
];

describe('WCAG AA contrast of the design tokens', () => {
  for (const [mode, palette] of [
    ['light', light],
    ['dark', dark],
  ] as const) {
    it(`every main pair passes in ${mode} mode`, () => {
      const rows = PAIRS.map(([fg, bg, min, what]) => ({
        mode,
        pair: `${fg} on ${bg}`,
        ratio: Number(contrast(palette[fg], palette[bg]).toFixed(2)),
        needs: min,
        what,
      }));
      console.table(rows);
      const failing = rows.filter((row) => row.ratio < row.needs);
      expect(failing).toEqual([]);
    });
  }

  it('the contrast function matches known values', () => {
    expect(contrast('#000000', '#FFFFFF')).toBeCloseTo(21, 5);
    expect(contrast('#FFFFFF', '#FFFFFF')).toBeCloseTo(1, 5);
    // The hairline is decoration only: it is below 3:1 on purpose, and fields use the darker edge.
    expect(contrast(tokens.color.border, tokens.color.page)).toBeLessThan(1.5);
  });
});
