// Design tokens: the single source of truth, taken from the Camera design reference. applyTokens()
// publishes them as CSS custom properties on :root, and every stylesheet reads them through var(--...).
// Light theme only (no dark mode). Style: Minimalism & Swiss: one accent, neutral greys, hairlines, no
// shadows or gradients, a strict 4px spacing scale.

export const tokens = {
  font: {
    /** Inter 400/600 from Google Fonts (index.html), then the system UI font. */
    family: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    baseSize: '14px',
    lineHeight: '1.5',
    lineHeightTight: '1.25',
    /** Four sizes: caption, body, section heading, page title. Hierarchy comes from size and weight only. */
    size: { 12: '12px', 14: '14px', 16: '16px', 24: '24px' },
    /** Two weights. */
    weight: { regular: '400', semibold: '600' },
  },
  color: {
    text: '#16181C',
    page: '#FFFFFF',
    textMuted: '#5B6170',
    /** The one hairline colour: cards, tables, dividers, buttons, the drawer and the top bar. */
    border: '#E3E5E9',
    /** Hover fill of a control. */
    hoverFill: '#F2F3F5',
    /** Pressed fill of a control. */
    activeFill: '#E8EAEE',
    /** The one accent: primary actions, links, the current item, the focus ring. */
    accent: '#1D4ED8',
    accentHover: '#163BA6',
    /** Text on an accent fill. */
    onAccent: '#FFFFFF',
    /**
     * Outline of text fields and the neutral dot/icon grey. The hairline #E3E5E9 is 1.26:1 on white, under
     * the 3:1 WCAG 1.4.11 asks for a field's edge, so fields use this darker grey (3.4:1).
     */
    fieldBorder: '#868C99',
    /** Error text, 6.5:1 on white. */
    danger: '#B42318',
    /** Camera status dots (always next to a text label). The only place status colours appear. */
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
    /** App screens: the content column never grows past this. */
    contentMaxWidth: '840px',
    /** Side gutter of the content on small screens. */
    gutter: '16px',
    controlHeight: '40px',
    controlHeightSmall: '36px',
    iconButton: '44px',
    navItemMinHeight: '44px',
    dayButtonWidth: '76px',
    dayButtonHeight: '60px',
    /** Every status dot. */
    statusDot: '8px',
    tableMinWidth: '560px',
  },
  radius: {
    /** Buttons, fields, chips. */
    control: '6px',
    /** Nav items, day buttons, table, cards, icon button. */
    card: '8px',
  },
  /** Strict 4px scale. */
  space: { 1: '4px', 2: '8px', 3: '12px', 4: '16px', 5: '24px', 6: '32px', 7: '40px', 8: '48px' },
  layout: {
    mainPadding: '40px 40px 72px',
    drawerPadding: '16px 12px',
    navItemPadding: '8px 12px',
    dayButtonPadding: '8px',
    summaryMargin: '16px 0 12px',
    headerCellPadding: '12px 16px',
    bodyCellPadding: '12px 16px',
    statusPadding: '4px 8px',
  },
  focusRing: { width: '2px', offset: '2px' },
  motion: { fast: '150ms' },
  /** Interaction states are defined once in global.css from these. */
  state: { disabledOpacity: '0.5' },
} as const;

const CAPITAL = /[A-Z]/g;

/** "accentTint" -> "accent-tint" */
function kebab(name: string): string {
  return name.replace(CAPITAL, (letter) => `-${letter.toLowerCase()}`);
}

/** Every token as a CSS custom property name and value, e.g. --color-accent: #1D4ED8. */
export function cssVariables(): Record<string, string> {
  const { font, color, size, radius, space, layout, focusRing, motion, state } = tokens;
  const vars: Record<string, string> = {
    '--font-family': font.family,
    '--font-size-base': font.baseSize,
    '--line-height': font.lineHeight,
    '--line-height-tight': font.lineHeightTight,
    '--font-weight-regular': font.weight.regular,
    '--font-weight-semibold': font.weight.semibold,
    '--focus-ring-width': focusRing.width,
    '--focus-ring-offset': focusRing.offset,
    '--motion-fast': motion.fast,
    '--opacity-disabled': state.disabledOpacity,
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
