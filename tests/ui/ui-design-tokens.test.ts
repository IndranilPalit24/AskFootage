import { describe, expect, it } from 'vitest';
import indexHtml from '../../web/index.html?raw';
import globalCss from '../../web/src/styles/global.css?raw';
import { applyTokens, cssVariables, tokens, TOKENS_STYLE_ID } from '../../web/src/styles/tokens';

describe('design tokens (Minimalism & Swiss Style)', () => {
  it('holds the target values', () => {
    // Colour: one accent, neutral greys, one hairline.
    expect(tokens.color.accent).toBe('#1D4ED8');
    expect(tokens.color.accentHover).toBe('#163BA6');
    expect(tokens.color.onAccent).toBe('#FFFFFF');
    expect(tokens.color.text).toBe('#16181C');
    expect(tokens.color.page).toBe('#FFFFFF');
    expect(tokens.color.textMuted).toBe('#5B6170');
    expect(tokens.color.border).toBe('#E3E5E9');
    expect(tokens.color.hoverFill).toBe('#F2F3F5');
    expect(tokens.color.activeFill).toBe('#E8EAEE');
    expect(tokens.color.fieldBorder).toBe('#868C99');
    // Status colours exist only for the camera status dots.
    expect(tokens.color.statusOnline).toBe('#16A34A');
    expect(tokens.color.statusStandby).toBe('#CA8A04');
    expect(tokens.color.statusOffline).toBe('#DC2626');
    // The tinted accent fills and the second border greys are gone.
    for (const removed of ['accentTint', 'accentTintBorder', 'readyText', 'readyBorder', 'controlBorder', 'rowDivider', 'tableHeaderFill', 'statusText', 'statusDot']) {
      expect(tokens.color).not.toHaveProperty(removed);
    }
    // Layout.
    expect(tokens.size.topbarHeight).toBe('56px');
    expect(tokens.size.drawerWidth).toBe('248px');
    expect(tokens.size.drawerWidthCollapsed).toBe('76px');
    expect(tokens.size.contentMaxWidth).toBe('840px');
    expect(tokens.size.gutter).toBe('16px');
    expect(tokens.size.controlHeight).toBe('40px');
    expect(tokens.size.controlHeightSmall).toBe('36px');
    expect(tokens.size.iconButton).toBe('44px');
    expect(tokens.size.navItemMinHeight).toBe('44px');
    expect(tokens.size.statusDot).toBe('8px');
    expect(tokens.layout.mainPadding).toBe('40px 40px 72px');
    // Radii: two only.
    expect(tokens.radius).toEqual({ control: '6px', card: '8px' });
    // Type: Inter, at most five sizes, two weights.
    expect(tokens.font.family.startsWith('Inter,')).toBe(true);
    expect(Object.keys(tokens.font.size).length).toBeLessThanOrEqual(5);
    expect(tokens.font.size).toEqual({ 12: '12px', 14: '14px', 16: '16px', 24: '24px' });
    expect(tokens.font.weight).toEqual({ regular: '400', semibold: '600' });
  });

  it('spacing is a strict 4px scale', () => {
    for (const value of Object.values(tokens.space)) expect(parseInt(value, 10) % 4).toBe(0);
    // Every length in the layout tokens is a multiple of 4 as well.
    for (const value of Object.values(tokens.layout)) {
      for (const length of value.match(/\d+/g)!) expect(Number(length) % 4).toBe(0);
    }
  });

  it('publishes them as CSS custom properties on :root', () => {
    applyTokens(document);
    applyTokens(document); // a second call refreshes, it does not add another <style>
    expect(document.querySelectorAll(`#${TOKENS_STYLE_ID}`)).toHaveLength(1);
    const css = document.getElementById(TOKENS_STYLE_ID)!.textContent!;
    expect(css).toContain('--color-accent: #1D4ED8;');
    expect(css).toContain('--color-border: #E3E5E9;');
    expect(css).toContain('--topbar-height: 56px;');
    expect(css).toContain('--drawer-width: 248px;');
    expect(css).toContain('--drawer-width-collapsed: 76px;');
    expect(css).toContain('--radius-control: 6px;');
    expect(css).toContain('--radius-card: 8px;');
    expect(css).toContain('--gutter: 16px;');
    expect(css).toContain('--status-dot: 8px;');
    expect(css).toContain('--font-weight-semibold: 600;');
    expect(css).not.toContain('--font-weight-medium');
  });

  it('the stylesheet only uses defined tokens and hard-codes no colour', () => {
    const defined = new Set(Object.keys(cssVariables()));
    const used = [...globalCss.matchAll(/var\((--[a-z0-9-]+)\)/g)].map((match) => match[1]);
    expect(used.length).toBeGreaterThan(50);
    expect(used.filter((name) => !defined.has(name))).toEqual([]);
    const hexes = [...globalCss.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((match) => match[0].toLowerCase());
    // No colour literal at all: every colour is a token.
    expect(hexes).toEqual([]);
    expect(globalCss).not.toMatch(/rgba?\(|hsla?\(/);
    // Only the two weights and the four sizes: no literal font weights or sizes.
    expect(globalCss).not.toMatch(/font-weight:\s*\d/);
    expect(globalCss).not.toMatch(/font-size:\s*[\d.]/);
    expect(globalCss).not.toMatch(/var\(--font-(weight-medium|size-(13|15))\)/);
    // Only the two radius tokens (50% for dots is the one other shape).
    expect(globalCss).not.toMatch(/border-radius:\s*\d+px/);
  });

  it('loads Inter and stays a light page', () => {
    // index.html (outside web/src) still requests 400;500;600: the unused 500 is harmless.
    expect(indexHtml).toContain('family=Inter:wght@400');
    expect(indexHtml).toContain('<meta name="color-scheme" content="light" />');
  });
});
