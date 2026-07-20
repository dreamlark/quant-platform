import { theme as antdTheme, type ThemeConfig } from 'antd';

// ============================================================
//  quant-platform Design System v2
//  基于 taste-skill (redesign-skill) 方法论重构
//  Design Read: Redesign-Overhaul / B2B Quant Dashboard
//  Dials: VARIANCE=4 | MOTION=4 | DENSITY=8
//  Aesthetic: Dark Tech Premium Terminal
// ============================================================

// ─── Color Tokens ───
export const TOKENS = {
  // Background layers (depth hierarchy)
  bgBase:        '#090c10',   // Deepest base
  bgSidebar:     '#0b0e14',   // Sidebar surface
  bgSurface:     '#111620',   // Card / container
  bgElevated:    '#1a2030',   // Popover / dropdown / modal
  bgHover:       'rgba(255,255,255,0.04)',

  // Border
  border:        'rgba(255,255,255,0.07)',
  borderStrong:  'rgba(255,255,255,0.12)',
  borderSubtle:  'rgba(255,255,255,0.04)',

  // Text
  textPrimary:   'rgba(255,255,255,0.92)',
  textSecondary: 'rgba(255,255,255,0.50)',
  textTertiary:  'rgba(255,255,255,0.28)',
  textDisabled:  'rgba(255,255,255,0.18)',

  // Accent (single considered accent - refined teal)
  accent:        '#00c9a7',
  accentHover:   '#00e6bc',
  accentMuted:   'rgba(0,201,167,0.15)',
  accentGlow:    'rgba(0,201,167,0.20)',

  // Semantic (stock market)
  up:            '#ff6363',   // Bullish - softer red
  upBg:          'rgba(255,99,99,0.12)',
  down:          '#4ade80',   // Bearish - modern green
  downBg:        'rgba(74,222,128,0.12)',
  warning:       '#f59e0b',
  warningBg:     'rgba(245,158,11,0.10)',

  // Category colors (factor / tech / sentiment / predict)
  factor:        '#38bdf8',   // Sky blue
  tech:          '#c084fc',   // Soft purple
  sentiment:     '#fb923c',   // Orange
  predict:       '#a78bfa',   // Lavender

  // Chart / grid
  grid:          'rgba(255,255,255,0.05)',
  axis:          'rgba(255,255,255,0.35)',
  axisLabel:     'rgba(255,255,255,0.45)',

  // Disclaimer
  disclaimerBg:  'rgba(245,158,11,0.06)',
  disclaimerBorder: 'rgba(245,158,11,0.14)',
} as const;

// ─── Typography Tokens ───
export const FONT = {
  display: "'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
  body:    "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
  mono:    "'JetBrains Mono', 'SF Mono', 'SF Pro Text', Menlo, Consolas, monospace",

  size: {
    xs:   '11px',
    sm:   '12px',
    base: '14px',
    lg:   '16px',
    xl:   '18px',
    '2xl': '22px',
    '3xl': '28px',
    '4xl': '36px',
  },

  weight: {
    regular: 400,
    medium:  500,
    semibold: 600,
    bold:    700,
    extrabold: 800,
  },

  lineHeight: {
    tight:   1.2,
    normal:  1.5,
    relaxed: 1.65,
  },
} as const;

// ─── Spacing Scale (4px base) ───
export const SPACE = {
  xs:  '4px',
  sm:  '8px',
  md:  '16px',
  lg:  '24px',
  xl:  '32px',
  '2xl':'48px',
} as const;

// ─── Radius Scale ───
export const RADIUS = {
  sm:  '6px',   // inputs, tags, small elements
  md:  '10px',  // cards, panels
  lg:  '14px',  // modals, large containers
  xl:  '18px',  // hero elements
} as const;

// ─── Shadow System (tinted) ───
export const SHADOW = {
  sm:   '0 1px 3px rgba(0,0,0,0.35)',
  md:   '0 4px 14px rgba(0,0,0,0.45)',
  lg:   '0 8px 30px rgba(0,0,0,0.55)',
  glow: `0 0 24px ${TOKENS.accentGlow}`,
  card: `0 1px 0 ${TOKENS.borderSubtle}, 0 4px 16px rgba(0,0,0,0.30)`,
  cardHover: `0 1px 0 ${TOKENS.border}, 0 8px 28px rgba(0,0,0,0.45), 0 0 40px ${TOKENS.accentGlow}`,
} as const;

// ─── Transition Tokens ───
export const TRANSITION = {
  fast:   '150ms cubic-bezier(0.16, 1, 0.3, 1)',
  normal: '250ms cubic-bezier(0.16, 1, 0.3, 1)',
  slow:   '400ms cubic-bezier(0.16, 1, 0.3, 1)',
  spring: '350ms cubic-bezier(0.34, 1.56, 0.64, 1)',
} as const;


// ════════════════════════════════════════════════
//  ANT DESIGN THEME CONFIGURATIONS
// ════════════════════════════════════════════════

/** Primary dark theme - the default experience */
export const darkTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: TOKENS.accent,
    colorInfo: TOKENS.factor,
    colorSuccess: TOKENS.down,
    colorWarning: TOKENS.warning,
    colorError: TOKENS.up,

    colorBgBase: TOKENS.bgBase,
    colorBgContainer: TOKENS.bgSurface,
    colorBgElevated: TOKENS.bgElevated,
    colorBgLayout: TOKENS.bgBase,
    colorBgSpotlight: TOKENS.accentMuted,

    colorBorder: TOKENS.border,
    colorBorderSecondary: TOKENS.borderSubtle,

    colorText: TOKENS.textPrimary,
    colorTextSecondary: TOKENS.textSecondary,
    colorTextTertiary: TOKENS.textTertiary,
    colorTextQuaternary: TOKENS.textDisabled,

    borderRadius: 10,
    borderRadiusSM: 6,
    borderRadiusLG: 14,

    fontSize: 14,
    fontSizeLG: 16,
    fontSizeSM: 12,
    fontSizeXL: 18,

    controlHeight: 36,
    controlHeightLG: 42,
    controlHeightSM: 30,

    fontFamily: FONT.body,

    wireframe: false,
  },
  components: {
    Card: {
      colorBorder: TOKENS.border,
      headerFontSize: 15,
      headerBg: 'transparent',
      paddingLG: 20,
      borderRadiusLG: parseInt(RADIUS.md),
    },
    Layout: {
      headerBg: 'transparent',
      bodyBg: TOKENS.bgBase,
      siderBg: TOKENS.bgSidebar,
      footerBg: TOKENS.bgBase,
    },
    Table: {
      headerBg: 'rgba(255,255,255,0.02)',
      headerColor: TOKENS.textSecondary,
      headerSortActiveBg: TOKENS.accentMuted,
      headerSortHoverBg: 'rgba(255,255,255,0.04)',
      rowHoverBg: TOKENS.bgHover,
      rowSelectedBg: TOKENS.accentMuted,
      borderColor: TOKENS.borderSubtle,
      cellFontSize: 13,
      cellPaddingBlockMD: 12,
      cellPaddingInlineMD: 14,
    },
    Menu: {
      darkItemBg: 'transparent',
      darkSubMenuItemBg: 'transparent',
      darkItemSelectedBg: TOKENS.accentMuted,
      darkItemSelectedColor: TOKENS.accent,
      itemBorderRadius: 6,
      itemMarginBlock: 2,
      itemMarginInline: 6,
      iconSize: 16,
      itemHeight: 40,
    },
    Statistic: {
      contentFontSize: 26,
    },
    Tag: {
      defaultBg: 'rgba(255,255,255,0.08)',
      defaultColor: TOKENS.textSecondary,
      borderRadiusSM: 5,
    },
    Button: {
      primaryShadow: `0 2px 8px ${TOKENS.accentGlow}`,
      contentFontSizeLG: 15,
      contentFontSizeSM: 13,
      fontWeight: 600,
      controlHeight: 34,
    },
    Select: {
      optionSelectedBg: TOKENS.accentMuted,
    },
    Input: {
      activeBorderColor: TOKENS.accent,
      hoverBorderColor: TOKENS.borderStrong,
      activeShadow: `0 0 0 2px ${TOKENS.accentMuted}`,
    },
    DatePicker: {
      activeBorderColor: TOKENS.accent,
      hoverBorderColor: TOKENS.borderStrong,
      cellActiveWithRangeBg: TOKENS.accentMuted,
    },
    Skeleton: {
      color: 'rgba(255,255,255,0.06)',
      colorGradientEnd: 'rgba(255,255,255,0.03)',
    },
    Tooltip: {
      colorBgSpotlight: TOKENS.bgElevated,
    },
    Progress: {
      defaultColor: TOKENS.accent,
      remainingColor: TOKENS.grid,
    },
  },
};

/** Light theme */
export const lightTheme: ThemeConfig = {
  algorithm: antdTheme.defaultAlgorithm,
  token: {
    colorPrimary: '#0d9488',
    colorBgBase: '#f8fafc',
    borderRadius: 10,
    fontSize: 14,
    fontFamily: FONT.body,
  },
};

/** Compact dark theme for power users */
export const compactDarkTheme: ThemeConfig = {
  algorithm: [antdTheme.darkAlgorithm, antdTheme.compactAlgorithm],
  token: {
    ...darkTheme.token!,
    borderRadius: 8,
    borderRadiusSM: 5,
    borderRadiusLG: 11,
    fontSize: 13,
    controlHeight: 32,
  },
  components: darkTheme.components,
};

/** Tech-blue theme (cyan-shifted terminal aesthetic) */
export const techBlueTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: '#0ef0b5',
    colorBgBase: '#070a10',
    colorBgContainer: '#0d1219',
    colorBgElevated: '#141c28',
    borderRadius: 10,
    fontSize: 14,
    colorText: '#e8f0f8',
    fontFamily: FONT.body,
  },
  components: {
    ...darkTheme.components,
    Menu: {
      ...(darkTheme.components?.Menu as object),
      darkItemSelectedBg: 'rgba(14,240,181,0.12)',
      darkItemSelectedColor: '#0ef0b5',
    } as Record<string, unknown>,
  },
};


// ════════════════════════════════════════════════
//  LEGACY COMPATIBILITY & EXPORTS
// ════════════════════════════════════════════════

export type ThemeMode = 'dark' | 'light' | 'compact' | 'techblue';

export const themeMap: Record<ThemeMode, ThemeConfig> = {
  dark: darkTheme,
  light: lightTheme,
  compact: compactDarkTheme,
  techblue: techBlueTheme,
};

export function getTheme(mode: ThemeMode): ThemeConfig {
  return themeMap[mode] || darkTheme;
}

// Legacy COLORS export (kept for backward compat with charts/pages)
export const COLORS = {
  up: TOKENS.up,
  down: TOKENS.down,
  factor: TOKENS.factor,
  tech: TOKENS.tech,
  sentiment: TOKENS.sentiment,
  predict: TOKENS.predict,
  grid: TOKENS.grid,
  axis: TOKENS.axis,
  axisLabel: TOKENS.axisLabel,
  accent: TOKENS.accent,
  accentMuted: TOKENS.accentMuted,
  accentHover: TOKENS.accentHover,
  upBg: TOKENS.upBg,
  downBg: TOKENS.downBg,
  warning: TOKENS.warning,
  warningBg: TOKENS.warningBg,
  bgSurface: TOKENS.bgSurface,
  bgElevated: TOKENS.bgElevated,
  textSecondary: TOKENS.textSecondary,
  textTertiary: TOKENS.textTertiary,
  border: TOKENS.border,
  borderStrong: TOKENS.borderStrong,
  borderSubtle: TOKENS.borderSubtle,
};

// Market temperature gauge coloring (0~100)
export function tempColor(v: number | null | undefined): string {
  if (v == null) return TOKENS.textTertiary;
  if (v >= 70) return TOKENS.up;
  if (v >= 45) return TOKENS.sentiment;
  if (v >= 25) return TOKENS.warning;
  return TOKENS.down;
}


// ════════════════════════════════════════════════
//  CSS VARIABLE MAPS (for index.css / App.tsx injection)
// ════════════════════════════════════════════════

// Define base theme CSS var maps (used as building blocks)
const _darkCSSVars = {
  '--bg-base': TOKENS.bgBase,
  '--bg-surface': TOKENS.bgSurface,
  '--bg-elevated': TOKENS.bgElevated,
  '--text-primary': TOKENS.textPrimary,
  '--text-secondary': TOKENS.textSecondary,
  '--text-tertiary': TOKENS.textTertiary,
  '--accent': TOKENS.accent,
  '--accent-muted': TOKENS.accentMuted,
  '--accent-glow': TOKENS.accentGlow,
  '--border': TOKENS.border,
  '--border-strong': TOKENS.borderStrong,
  '--up-color': TOKENS.up,
  '--down-color': TOKENS.down,
  '--up-bg': TOKENS.upBg,
  '--down-bg': TOKENS.downBg,
  '--disclaimer-bg': TOKENS.disclaimerBg,
  '--disclaimer-border': TOKENS.disclaimerBorder,
  '--font-display': FONT.display,
  '--font-mono': FONT.mono,
  '--shadow-card': SHADOW.card,
  '--shadow-card-hover': SHADOW.cardHover,
  '--radius-md': RADIUS.md,
  '--radius-sm': RADIUS.sm,
  '--transition-normal': TRANSITION.normal,
};

export const themeCSSVars: Record<ThemeMode, Record<string, string>> = {
  dark: { ..._darkCSSVars },
  light: {
    '--bg-base': '#f8fafc',
    '--bg-surface': '#ffffff',
    '--bg-elevated': '#ffffff',
    '--text-primary': 'rgba(0,0,0,0.88)',
    '--text-secondary': 'rgba(0,0,0,0.50)',
    '--text-tertiary': 'rgba(0,0,0,0.28)',
    '--accent': '#0d9488',
    '--accent-muted': 'rgba(13,148,136,0.10)',
    '--accent-glow': 'rgba(13,148,136,0.15)',
    '--border': 'rgba(0,0,0,0.08)',
    '--border-strong': 'rgba(0,0,0,0.15)',
    '--up-color': '#dc2626',
    '--down-color': '#16a34a',
    '--up-bg': 'rgba(220,38,38,0.08)',
    '--down-bg': 'rgba(22,163,74,0.08)',
    '--disclaimer-bg': TOKENS.disclaimerBg,
    '--disclaimer-border': TOKENS.disclaimerBorder,
    '--font-display': FONT.display,
    '--font-mono': FONT.mono,
    '--shadow-card': SHADOW.sm,
    '--shadow-card-hover': SHADOW.md,
    '--radius-md': RADIUS.md,
    '--radius-sm': RADIUS.sm,
    '--transition-normal': TRANSITION.normal,
  },
  compact: { ..._darkCSSVars },
  techblue: {
    '--bg-base': '#070a10',
    '--bg-surface': '#0d1219',
    '--bg-elevated': '#141c28',
    '--text-primary': '#e8f0f8',
    '--text-secondary': 'rgba(232,240,248,0.50)',
    '--text-tertiary': 'rgba(232,240,248,0.28)',
    '--accent': '#0ef0b5',
    '--accent-muted': 'rgba(14,240,181,0.12)',
    '--accent-glow': 'rgba(14,240,181,0.18)',
    '--border': 'rgba(255,255,255,0.07)',
    '--border-strong': 'rgba(255,255,255,0.12)',
    '--up-color': TOKENS.up,
    '--down-color': TOKENS.down,
    '--up-bg': TOKENS.upBg,
    '--down-bg': TOKENS.downBg,
    '--disclaimer-bg': 'rgba(14,240,181,0.06)',
    '--disclaimer-border': 'rgba(14,240,181,0.14)',
    '--font-display': FONT.display,
    '--font-mono': FONT.mono,
    '--shadow-card': SHADOW.card,
    '--shadow-card-hover': SHADOW.cardHover,
    '--radius-md': RADIUS.md,
    '--radius-sm': RADIUS.sm,
    '--transition-normal': TRANSITION.normal,
  },
};
