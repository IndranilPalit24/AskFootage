import { describe, expect, it } from 'vitest';
import indexHtml from '../../web/index.html?raw';
import mainSource from '../../web/src/main.tsx?raw';
import globalCss from '../../web/src/styles/global.css?raw';
import { applyTokens, cssVariables, tokens, TOKENS_STYLE_ID, tokensCss } from '../../web/src/styles/tokens';

describe('design tokens (calm, precise review tool)', () => {
  it('holds the target values', () => {
    // Colour: one accent, neutral greys, one hairline.
    expect(tokens.color.accent).toBe('#005FCE'); // CHANGED: sampled from board.png (was #1D4ED8)
    expect(tokens.color.accentHover).toBe('#004CA6');
    expect(tokens.color.onAccent).toBe('#FFFFFF');
    expect(tokens.color.text).toBe('#16181C');
    expect(tokens.color.page).toBe('#FFFFFF');
    expect(tokens.color.textMuted).toBe('#5B6170');
    expect(tokens.color.border).toBe('#E3E5E9');
    expect(tokens.color.hoverFill).toBe('#F2F3F5');
    expect(tokens.color.activeFill).toBe('#E8EAEE');
    expect(tokens.color.fieldBorder).toBe('#868C99');
    // Sign-in page (CHANGED on purpose): the warm panel is sampled from the reference (was #F7F5F1); two colours added.
    expect(tokens.color.surfaceWarm).toBe('#F5F3F1');
    expect(tokens.color.planBlue).toBe('#2F5FA8');
    expect(tokens.color.buttonBorder).toBe('#D5D8DE');
    // Status colours exist only for the camera status dots.
    expect(tokens.color.statusOnline).toBe('#16A34A');
    expect(tokens.color.statusStandby).toBe('#CA8A04');
    expect(tokens.color.statusOffline).toBe('#DC2626');
    // The tinted accent fills and the second border greys are gone.
    for (const removed of ['accentTint', 'accentTintBorder', 'readyText', 'readyBorder', 'controlBorder', 'rowDivider', 'tableHeaderFill', 'statusText', 'statusDot']) {
      expect(tokens.color).not.toHaveProperty(removed);
    }
    // Layout.
    expect(tokens.size.topbarHeight).toBe('52px');
    expect(tokens.size.drawerWidth).toBe('208px');
    expect(tokens.size.drawerWidthCollapsed).toBe('76px');
    expect(tokens.size.contentMaxWidth).toBe('840px');
    expect(tokens.size.gutter).toBe('16px');
    expect(tokens.size.controlHeight).toBe('36px');
    expect(tokens.size.controlHeightSmall).toBe('32px');
    expect(tokens.size.iconButton).toBe('44px');
    expect(tokens.size.navItemMinHeight).toBe('40px');
    expect(tokens.size.statusDot).toBe('8px');
    expect(tokens.layout.mainPadding).toBe('20px 28px 12px');
    // Radii: two only.
    expect(tokens.radius).toEqual({ control: '6px', card: '8px' });
    // Type: Inter at six sizes and three weights. CHANGED on purpose (was 12/14/16/24/32 and 400/600): the
    // review-tool redesign needs a 13px dense size for tables and cards, 20px page titles, one 28px focal
    // headline and a 500 weight for labels and buttons.
    expect(tokens.font.family.startsWith('Inter,')).toBe(true);
    expect(Object.keys(tokens.font.size).length).toBeLessThanOrEqual(6);
    expect(tokens.font.size).toEqual({ 12: '11px', 13: '12px', 14: '13px', 16: '14.5px', 20: '24px', 28: '26px' });
    expect(tokens.font.weight).toEqual({ regular: '400', medium: '500', semibold: '600' });
    // Ids and timestamps use a monospace stack (always with tabular numerals).
    expect(tokens.font.mono).toContain('monospace');
    // New in the redesign: the player letterbox, the canvas behind cards, and the three-step elevation scale.
    expect(tokens.color.playerBg).toBe('#0B0F17');
    expect(tokens.color.canvas).toBe(tokens.color.surface);
    expect(Object.keys(tokens.elevation)).toEqual(['0', '1', '2']);
    expect(tokens.elevation[0]).toBe('none');
    for (const shadow of [tokens.elevation[1], tokens.elevation[2]]) expect(shadow).not.toMatch(/gradient|inset/);
    // Reference pass: the cobalt tint of the current sidebar item exists in both palettes.
    expect(tokens.color.accentSubtle).toBe('#E6F0FB');
    // One theme: no dark palette and no dark media query is published.
    expect(tokensCss()).not.toContain('prefers-color-scheme');
    expect(tokens.size.resultFrameWidth).toBe('320px');
    expect(tokens.size.railWidth).toBe('360px');
    expect(tokens.size.workspaceMaxWidth).toBe('1280px');
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
    expect(css).toContain('--color-accent: #005FCE;');
    expect(css).toContain('--color-border: #E3E5E9;');
    expect(css).toContain('--topbar-height: 52px;');
    expect(css).toContain('--drawer-width: 208px;');
    expect(css).toContain('--drawer-width-collapsed: 76px;');
    expect(css).toContain('--radius-control: 6px;');
    expect(css).toContain('--radius-card: 8px;');
    expect(css).toContain('--gutter: 16px;');
    expect(css).toContain('--status-dot: 8px;');
    expect(css).toContain('--font-weight-medium: 500;');
    expect(css).toContain('--font-weight-semibold: 600;');
    expect(css).toContain('--elevation-0: none;');
    expect(css).toContain('--elevation-1:');
    expect(css).toContain('--elevation-2:');
    expect(css).toContain('--color-player-bg: #0B0F17;');
    expect(css).toContain('--font-mono:');
    // No bold: only 400, 500 and 600 exist.
    expect(css).not.toContain('--font-weight-bold');
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
    // Only the token weights and sizes: no literal font weights or sizes, and nothing off the scale.
    expect(globalCss).not.toMatch(/font-weight:\s*\d/);
    expect(globalCss).not.toMatch(/font-size:\s*[\d.]/);
    expect(globalCss).not.toMatch(/var\(--font-(weight-bold|size-(15|24|32))\)/);
    // Only the two radius tokens (50% for dots is the one other shape).
    expect(globalCss).not.toMatch(/border-radius:\s*\d+px/);
  });

  it('bundles Inter in exactly the three token weights (no font request leaves the app) and follows the system light or dark setting', () => {
    // CHANGED on purpose (was a Google Fonts link for 400 and 600): the font now ships with the app.
    expect(indexHtml).not.toMatch(/fonts\.googleapis|fonts\.gstatic/);
    for (const weight of ['400', '500', '600']) expect(mainSource).toContain('@fontsource/inter/latin-' + weight + '.css');
    expect(mainSource).not.toMatch(/@fontsource\/inter\/latin-(100|200|300|700|800|900)/);
    expect(indexHtml).toContain('<meta name="color-scheme" content="light" />');
    // A real favicon instead of an empty data: URL.
    expect(indexHtml).toContain('<link rel="icon" href="/favicon.svg" type="image/svg+xml" />');
  });

  it('holds the trust colours and the welcome page layout tokens', () => {
    expect(tokens.color.navy).toBe('#0F1F3D');
    expect(tokens.color.onNavy).toBe('#FFFFFF');
    expect(tokens.color.surface).toBe('#F8F8F9');
    expect(tokens.color.evidenceBox).toBe('#DC2626');
    expect(tokens.size.landingMaxWidth).toBe('1120px');
    expect(tokens.size.contentMaxWidth).toBe('840px');
    applyTokens(document);
    const css = document.getElementById(TOKENS_STYLE_ID)!.textContent!;
    expect(css).toContain('--color-navy: #0F1F3D;');
    expect(css).toContain('--landing-max-width: 1120px;');
    // CHANGED on purpose: the welcome headline moves from 32px to the 28px focal size of the new scale.
    expect(css).toContain('--font-size-28: 26px;');
    expect(css).not.toContain('--font-size-32');
    expect(css).toContain('--space-9: 64px;');
  });
});
