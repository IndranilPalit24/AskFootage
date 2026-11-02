// Design tokens: the single source of truth, taken from the Camera design reference. applyTokens()
// publishes them as CSS custom properties on :root, and every stylesheet reads them through var(--...).
// Three layers: primitives (the raw hex values below), semantic tokens (color.text, color.accent, ...)
// that the stylesheet reads, and component rules in global.css that only ever use the semantic ones.
// One theme only: the light reference theme, whatever the system setting (no dark palette, no toggle).
// Style: a calm, precise review tool: one accent, neutral cool greys, hairlines, an elevation scale of
// three steps (0 none, 1 hairline lift, 2 raised), no gradients or glow, a strict 4px spacing scale.
// The app canvas is the light grey (surface) with white cards on it; the player sits on a dark letterbox.

export const tokens = {
  font: {
    /** Inter 400/500/600, bundled with the app (@fontsource/inter, imported in main.tsx), then the system UI font. */
    family: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    /** Ids, camera numbers and timestamps. Always paired with tabular numerals. */
    mono: 'ui-monospace, SFMono-Regular, "Cascadia Mono", Menlo, Consolas, "Liberation Mono", monospace',
    baseSize: '16px',
    lineHeight: '1.5',
    lineHeightTight: '1.25',
    /**
     * Six sizes: 12 caption and section label, 13 dense table and card text, 14 body, 16 section heading,
     * 20 page title, 28 the one focal headline (Find Footage start, welcome page). Hierarchy comes from
     * size and weight only.
     */
    size: { 12: '13px', 13: '15px', 14: '16px', 16: '18px', 20: '32px', 28: '40px' },
    /** Three weights: text, labels and buttons, titles. */
    weight: { regular: '400', medium: '500', semibold: '600' },
  },
  color: {
    text: '#16181C',
    page: '#FFFFFF',
    /** The app canvas behind the cards (the cards and bars are the page colour); same grey as surface in light. */
    canvas: '#F8F8F9',
    /** The sign-in page's brand panel: a warm off-white (sampled from the reference); muted text on it is 5.5:1. */
    surfaceWarm: '#F5F3F1',
    textMuted: '#5B6170',
    /** The one hairline colour: cards, tables, dividers, buttons, the drawer and the top bar. */
    border: '#E3E5E9',
    /** The sign-in page's floor plan and travel path: a muted blue, decoration only. */
    planBlue: '#2F5FA8',
    /** Outline of the secondary sign-in button (decoration around text that is 15:1; a 1px edge). */
    buttonBorder: '#D5D8DE',
    /** The sidebar (sampled from the reference board) and the grey panel behind "Why this matched". */
    sidebar: '#F1F2F4',
    panelFill: '#F3F5F6',
    /** Sidebar item text. */
    navText: '#3D495C',
    /** Hover fill of a control. */
    hoverFill: '#F2F3F5',
    /** Pressed fill of a control. */
    activeFill: '#E8EAEE',
    /** The one accent: primary actions, links, the current item, the focus ring. */
    accent: '#005FCE',
    accentHover: '#004CA6',
    /** The current page's row in the sidebar: a faint cobalt tint (accent text on it is 6.0:1). */
    accentSubtle: '#E6F0FB',
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
    // Trust colours, used by the welcome page. The trust blue is the accent above.
    /** Deep navy: the welcome page's hero and closing bands. */
    navy: '#0F1F3D',
    /** Headings on the page background (navy). */
    heading: '#0F1F3D',
    /** Text and the focus ring on navy, 16.4:1. */
    onNavy: '#FFFFFF',
    /** Secondary text on navy, 10.1:1. */
    onNavyMuted: '#C3CCDD',
    /** Hairline on navy (decoration only, like the hairline on white). */
    navyBorder: '#33476B',
    /** Light grey behind alternate welcome sections; muted text on it is 5.8:1. */
    surface: '#F8F8F9',
    /** Outline of a matched object on an evidence frame, and its label fill (white label text 4.8:1). */
    evidenceBox: '#DC2626',
    /** The player letterbox and the scrubber panel: near-black. */
    playerBg: '#0B0F17',
    /** Text on the player letterbox (15.8:1) and the quieter readout text (8.3:1). */
    onPlayer: '#E6E9EF',
    onPlayerMuted: '#A3ABBC',
    /** The accent on the letterbox: a light blue, 8.4:1 on the letterbox (the accent is under 3:1 on it). */
    playerAccent: '#8CAAF8',
    /** Scrubber track on the letterbox, and the hairline of the player panel. */
    playerTrack: '#2A3448',
  },
  size: {
    topbarHeight: '72px',
    drawerWidth: '216px',
    drawerWidthCollapsed: '76px',
    /** App screens: the content column never grows past this. */
    contentMaxWidth: '840px',
    /** The welcome page's content column. */
    landingMaxWidth: '1120px',
    /** The welcome hero's column (headline, ask box, examples). */
    heroWidth: '720px',
    /** Longest line of running text on the welcome page. */
    textMeasure: '640px',
    /** Side gutter of the content on small screens. */
    gutter: '16px',
    /** Clip detail and tables: the wider workspace column, and the evidence rail beside the player. */
    wideMaxWidth: '1120px',
    workspaceMaxWidth: '1280px',
    railWidth: '360px',
    /** A result card's poster frame (16:9) and the small poster in a table row. */
    posterWidth: '192px',
    rowPosterWidth: '64px',
    controlHeight: '40px',
    controlHeightSmall: '36px',
    iconButton: '44px',
    /** Result card poster frame (4:3) and the thumbnail of a saved clip or a compact match row. */
    resultFrameWidth: '320px',
    thumbWidth: '160px',
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
  space: { 1: '4px', 2: '8px', 3: '12px', 4: '16px', 5: '24px', 6: '32px', 7: '40px', 8: '48px', 9: '64px', 10: '80px' },
  layout: {
    mainPadding: '28px 32px 64px',
    drawerPadding: '16px 12px',
    navItemPadding: '8px 12px',
    dayButtonPadding: '8px',
    summaryMargin: '16px 0 12px',
    headerCellPadding: '12px 16px',
    bodyCellPadding: '12px 16px',
    statusPadding: '4px 8px',
  },
  focusRing: { width: '2px', offset: '2px' },
  /** Elevation: 0 flat (hairline only), 1 a card on the canvas, 2 a popover, dialog or toast. */
  elevation: {
    0: 'none',
    1: '0 1px 2px rgba(15, 31, 61, 0.08)',
    2: '0 4px 12px rgba(15, 31, 61, 0.14)',
  },
  /** 150ms ease-out on hover and focus (the 120 to 180 ms band); switched off for reduced motion. */
  motion: { fast: '150ms', ease: 'cubic-bezier(0.2, 0, 0, 1)' },
  /** Interaction states are defined once in global.css from these. */
  state: { disabledOpacity: '0.5' },
} as const;

const CAPITAL = /[A-Z]/g;

/** "accentTint" -> "accent-tint" */
function kebab(name: string): string {
  return name.replace(CAPITAL, (letter) => `-${letter.toLowerCase()}`);
}

/** Every token as a CSS custom property name and value, e.g. --color-accent: #005FCE. */
export function cssVariables(): Record<string, string> {
  const { font, color, size, radius, space, layout, focusRing, motion, state, elevation } = tokens;
  const vars: Record<string, string> = {
    '--font-family': font.family,
    '--font-mono': font.mono,
    '--font-size-base': font.baseSize,
    '--line-height': font.lineHeight,
    '--line-height-tight': font.lineHeightTight,
    '--font-weight-regular': font.weight.regular,
    '--font-weight-medium': font.weight.medium,
    '--font-weight-semibold': font.weight.semibold,
    '--focus-ring-width': focusRing.width,
    '--focus-ring-offset': focusRing.offset,
    '--motion-fast': motion.fast,
    '--motion-ease': motion.ease,
    '--opacity-disabled': state.disabledOpacity,
  };
  for (const [step, value] of Object.entries(elevation)) vars[`--elevation-${step}`] = value;
  for (const [step, value] of Object.entries(font.size)) vars[`--font-size-${step}`] = value;
  for (const [name, value] of Object.entries(color)) vars[`--color-${kebab(name)}`] = value;
  for (const [name, value] of Object.entries(size)) vars[`--${kebab(name)}`] = value;
  for (const [name, value] of Object.entries(radius)) vars[`--radius-${kebab(name)}`] = value;
  for (const [step, value] of Object.entries(space)) vars[`--space-${step}`] = value;
  for (const [name, value] of Object.entries(layout)) vars[`--${kebab(name)}`] = value;
  return vars;
}

function declarations(vars: Record<string, string>, indent: string): string {
  return Object.entries(vars)
    .map(([name, value]) => `${indent}${name}: ${value};`)
    .join('\n');
}

/** The tokens as one :root rule. There is one theme only: light. */
export function tokensCss(): string {
  return `:root {
${declarations(cssVariables(), '  ')}
}
`;
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
