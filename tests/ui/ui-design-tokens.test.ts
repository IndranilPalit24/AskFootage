import { describe, expect, it } from 'vitest';
import indexHtml from '../../web/index.html?raw';
import globalCss from '../../web/src/styles/global.css?raw';
import { applyTokens, cssVariables, tokens, TOKENS_STYLE_ID } from '../../web/src/styles/tokens';

describe('design tokens (Camera design reference)', () => {
  it('holds the reference values', () => {
    expect(tokens.color.accent).toBe('#1D4ED8');
    expect(tokens.color.accentHover).toBe('#163BA6');
    expect(tokens.color.accentTint).toBe('#EEF2FD');
    expect(tokens.color.accentTintBorder).toBe('#D8E1FA');
    expect(tokens.color.border).toBe('#E3E5E9');
    expect(tokens.color.controlBorder).toBe('#D5D8DE');
    expect(tokens.color.text).toBe('#16181C');
    expect(tokens.color.page).toBe('#FFFFFF');
    expect(tokens.color.textMuted).toBe('#5B6170');
    expect(tokens.color.hoverFill).toBe('#F2F3F5');
    expect(tokens.color.tableHeaderFill).toBe('#FAFBFC');
    expect(tokens.color.rowDivider).toBe('#EDEEF1');
    expect(tokens.color.readyText).toBe('#1A44BE');
    expect(tokens.color.readyBorder).toBe('#C3D1F5');
    expect(tokens.color.statusText).toBe('#4A505C');
    expect(tokens.color.statusDot).toBe('#868C99');
    expect(tokens.size.topbarHeight).toBe('56px');
    expect(tokens.size.drawerWidth).toBe('248px');
    expect(tokens.size.drawerWidthCollapsed).toBe('76px');
    expect(tokens.size.contentMaxWidth).toBe('840px');
    expect(tokens.size.controlHeight).toBe('40px');
    expect(tokens.size.controlHeightSmall).toBe('36px');
    expect(tokens.size.iconButton).toBe('44px');
    expect(tokens.size.navItemMinHeight).toBe('44px');
    expect(tokens.radius.control).toBe('6px');
    expect(tokens.radius.card).toBe('8px');
    expect(tokens.radius.focus).toBe('4px');
    expect(tokens.layout.mainPadding).toBe('40px 40px 72px');
    expect(tokens.font.family.startsWith('Inter,')).toBe(true);
    expect(tokens.font.weight).toEqual({ regular: '400', medium: '500', semibold: '600' });
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
  });

  it('the stylesheet only uses defined tokens and hard-codes no colour', () => {
    const defined = new Set(Object.keys(cssVariables()));
    const used = [...globalCss.matchAll(/var\((--[a-z0-9-]+)\)/g)].map((match) => match[1]);
    expect(used.length).toBeGreaterThan(50);
    expect(used.filter((name) => !defined.has(name))).toEqual([]);
    const hexes = [...globalCss.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((match) => match[0].toLowerCase());
    expect(new Set(hexes)).toEqual(new Set(['#ffffff', '#000000']));
    // Minimal: no gradients, no shadows.
    expect(globalCss).not.toMatch(/(linear|radial|conic)-gradient\(|box-shadow\s*:/);
  });

  it('loads Inter 400/500/600 and stays a light page', () => {
    expect(indexHtml).toContain('family=Inter:wght@400;500;600');
    expect(indexHtml).toContain('<meta name="color-scheme" content="light" />');
  });
});
