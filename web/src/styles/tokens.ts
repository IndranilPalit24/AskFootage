// Design tokens: the single source of truth, taken from the Camera design reference. applyTokens()
// publishes them as CSS custom properties on :root, and every stylesheet reads them through var(--...).
// Light theme.

export const tokens = {
  font: {
    /** Inter 400/500/600 from Google Fonts (index.html), then the system UI font. */
    family: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    baseSize: '14px',
    lineHeight: '1.5',
    size: { 12: '12px', 13: '13px', 14: '14px', 15: '15px', 16: '16px', 24: '24px' },
    weight: { regular: '400', medium: '500', semibold: '600' },
    /** Brand and page titles. */
    tightTracking: '-0.01em',
  },
  color: {
    text: '#16181C',
    page: '#FFFFFF',
    textMuted: '#5B6170',
    border: '#E3E5E9',
    controlBorder: '#D5D8DE',
    hoverFill: '#F2F3F5',
    tableHeaderFill: '#FAFBFC',
    rowDivider: '#EDEEF1',
    accent: '#1D4ED8',
    accentHover: '#163BA6',
    accentTint: '#EEF2FD',
    accentTintBorder: '#D8E1FA',
    readyText: '#1A44BE',
    readyBorder: '#C3D1F5',
    statusText: '#4A505C',
    statusDot: '#868C99',
    /**
     * Outline of text fields. Not in the reference (the Camera screen has none): the control border
     * #D5D8DE is 1.4:1 on white, under the 3:1 WCAG 1.4.11 asks for a field's edge, so fields reuse the
     * status-dot grey (3.4:1).
     */
    fieldBorder: '#868C99',
    /** Not in the reference: error text, 6.5:1 on white. */
    danger: '#B42318',
    /** Camera status dots (always next to a text label). */
    statusOnline: '#16A34A',
    statusStandby: '#CA8A04',
    statusOffline: '#DC2626',
    /** Behind a dialog. */
    scrim: 'rgba(22, 24, 28, 0.45)',
  },
  size: {
    topbarHeight: '56px',
    drawerWidth: '248px',
    drawerWidthCollapsed: '76px',
    contentMaxWidth: '840px',
    controlHeight: '40px',
    controlHeightSmall: '36px',
    iconButton: '44px',
    navItemMinHeight: '44px',
    icon: '18px',
    dayButtonWidth: '76px',
    dayButtonHeight: '60px',
    statusDot: '6px',
    /** The Cameras page status dot. */
    cameraStatusDot: '8px',
    tableMinWidth: '560px',
  },
  radius: {
    /** Buttons, fields. */
    control: '6px',
    /** Nav items, day buttons, table, cards, icon button. */
    card: '8px',
    /** The focus ring. */
    focus: '4px',
    pill: '999px',
  },
  space: { 1: '4px', 2: '8px', 3: '12px', 4: '16px', 5: '24px', 6: '32px' },
  layout: {
    mainPadding: '40px 40px 72px',
    drawerPadding: '16px 12px',
    navItemPadding: '10px 12px',
    dayButtonPadding: '10px 8px',
    summaryMargin: '20px 0 12px',
    headerCellPadding: '12px 16px',
    bodyCellPadding: '14px 16px',
    statusPadding: '3px 10px',
  },
  focusRing: { width: '2px', offset: '2px' },
  motion: { drawer: '150ms' },
} as const;

const CAPITAL = /[A-Z]/g;

/** "accentTint" -> "accent-tint" */
function kebab(name: string): string {
  return name.replace(CAPITAL, (letter) => `-${letter.toLowerCase()}`);
}

/** Every token as a CSS custom property name and value, e.g. --color-accent: #1D4ED8. */
export function cssVariables(): Record<string, string> {
  const { font, color, size, radius, space, layout, focusRing, motion } = tokens;
  const vars: Record<string, string> = {
    '--font-family': font.family,
    '--font-size-base': font.baseSize,
    '--line-height': font.lineHeight,
    '--font-weight-regular': font.weight.regular,
    '--font-weight-medium': font.weight.medium,
    '--font-weight-semibold': font.weight.semibold,
    '--tight-tracking': font.tightTracking,
    '--focus-ring-width': focusRing.width,
    '--focus-ring-offset': focusRing.offset,
    '--drawer-transition': motion.drawer,
  };
  for (const [step, value] of Object.entries(font.size)) vars[`--font-size-${step}`] = value;
  for (const [name, value] of Object.entries(color)) vars[`--color-${kebab(name)}`] = value;
  for (const [name, value] of Object.entries(size)) vars[`--${kebab(name)}`] = value;
  for (const [name, value] of Object.entries(radius)) vars[`--radius-${kebab(name)}`] = value;
  for (const [step, value] of Object.entries(space)) vars[`--space-${step}`] = value;
  for (const [name, value] of Object.entries(layout)) vars[`--${kebab(name)}`] = value;
  return vars;
}

/** The tokens as one :root rule. */
export function tokensCss(): string {
  const body = Object.entries(cssVariables())
    .map(([name, value]) => `  ${name}: ${value};`)
    .join('\n');
  return `:root {\n${body}\n}\n`;
}

export const TOKENS_STYLE_ID = 'askfootage-tokens';

/** Publishes the tokens on :root (once; calling again refreshes the same <style> element). */
export function applyTokens(doc: Document = document): void {
  let style = doc.getElementById(TOKENS_STYLE_ID);
  if (!style) {
    style = doc.createElement('style');
    style.id = TOKENS_STYLE_ID;
    doc.head.prepend(style);
  }
  style.textContent = tokensCss();
}
