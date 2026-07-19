import { theme as antdTheme, type ThemeConfig } from 'antd';

// 暗色现代风主题（AntD darkAlgorithm）
// 设计原则：基底最深 → 卡片/侧栏次级 → 浮层最亮，制造明确视觉纵深。
// 主色与金融语义色沿用仓库既定取值，仅增强层次与控件质感。
export const darkTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: '#177ddc',
    colorBgBase: '#0e1116',
    colorBgContainer: '#171b22',
    colorBgElevated: '#1f242d',
    colorBorder: 'rgba(255,255,255,0.08)',
    colorBorderSecondary: 'rgba(255,255,255,0.06)',
    colorTextBase: 'rgba(255,255,255,0.88)',
    borderRadius: 10,
    fontSize: 14,
    controlHeight: 34,
  },
  components: {
    Card: {
      colorBorder: 'rgba(255,255,255,0.08)',
      headerFontSize: 15,
    },
    Layout: {
      headerBg: 'transparent',
      bodyBg: '#0e1116',
      siderBg: '#0b0d12',
    },
    Table: {
      headerBg: 'rgba(255,255,255,0.03)',
      headerColor: 'rgba(255,255,255,0.65)',
      rowHoverBg: 'rgba(23,125,220,0.10)',
      borderColor: 'rgba(255,255,255,0.06)',
    },
    Menu: {
      darkItemBg: 'transparent',
      darkSubMenuItemBg: 'transparent',
    },
    Statistic: {
      contentFontSize: 24,
    },
  },
};

// 亮色主题
export const lightTheme: ThemeConfig = {
  algorithm: antdTheme.defaultAlgorithm,
  token: {
    colorPrimary: '#1677ff',
    colorBgBase: '#ffffff',
    borderRadius: 8,
    fontSize: 14,
  },
};

// 紧凑暗色主题
export const compactDarkTheme: ThemeConfig = {
  algorithm: [antdTheme.darkAlgorithm, antdTheme.compactAlgorithm],
  token: {
    colorPrimary: '#177ddc',
    colorBgBase: '#0e1116',
    borderRadius: 6,
    fontSize: 13,
  },
};

// 科技蓝主题（暗色底 + 蓝色调）
export const techBlueTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: '#00d4ff',
    colorBgBase: '#0a0e27',
    colorBgContainer: '#111634',
    colorBgElevated: '#1a1f4a',
    borderRadius: 10,
    fontSize: 14,
    colorTextBase: '#e0e6ff',
  },
};

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

export const COLORS = {
  up: '#cf1322', // 涨（红）
  down: '#3f8600', // 跌（绿）
  factor: '#177ddc',
  tech: '#722ed1',
  sentiment: '#fa8c16',
  predict: '#13c2c2',
  grid: 'rgba(255,255,255,0.06)',
  axis: 'rgba(255,255,255,0.45)',
  axisLabel: 'rgba(255,255,255,0.6)',
};

// 市场温度计分档配色（0~100）
export function tempColor(v: number | null | undefined): string {
  if (v == null) return COLORS.axisLabel;
  if (v >= 70) return COLORS.up;
  if (v >= 45) return COLORS.sentiment;
  if (v >= 25) return '#eab308';
  return COLORS.down;
}

// 各主题对应的 CSS 变量（供 index.css / App.tsx 注入）
export const themeCSSVars: Record<ThemeMode, Record<string, string>> = {
  dark: {
    '--bg-base': '#0e1116',
    '--text-primary': 'rgba(255,255,255,0.88)',
    '--text-secondary': 'rgba(255,255,255,0.45)',
    '--disclaimer-bg': 'rgba(250,173,20,0.08)',
    '--disclaimer-border': 'rgba(250,173,20,0.18)',
  },
  light: {
    '--bg-base': '#f0f2f5',
    '--text-primary': 'rgba(0,0,0,0.88)',
    '--text-secondary': 'rgba(0,0,0,0.45)',
    '--disclaimer-bg': 'rgba(250,173,20,0.06)',
    '--disclaimer-border': 'rgba(250,173,20,0.15)',
  },
  compact: {
    '--bg-base': '#0e1116',
    '--text-primary': 'rgba(255,255,255,0.88)',
    '--text-secondary': 'rgba(255,255,255,0.45)',
    '--disclaimer-bg': 'rgba(250,173,20,0.08)',
    '--disclaimer-border': 'rgba(250,173,20,0.18)',
  },
  techblue: {
    '--bg-base': '#0a0e27',
    '--text-primary': '#e0e6ff',
    '--text-secondary': 'rgba(224,230,255,0.45)',
    '--disclaimer-bg': 'rgba(0,212,255,0.08)',
    '--disclaimer-border': 'rgba(0,212,255,0.2)',
  },
};
