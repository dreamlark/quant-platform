import { theme as antdTheme, type ThemeConfig } from 'antd';

// 暗色现代风主题
export const darkTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: '#177ddc',
    colorBgBase: '#141414',
    borderRadius: 8,
    fontSize: 14,
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
    colorBgBase: '#141414',
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
  up: '#cf1322', // 涨（A 股红）
  down: '#3f8600', // 跌（A 股绿）
  factor: '#177ddc',
  tech: '#722ed1',
  sentiment: '#fa8c16',
  predict: '#13c2c2',
};

// 亮色主题下的 CSS 变量
export const themeCSSVars: Record<ThemeMode, Record<string, string>> = {
  dark: {
    '--bg-base': '#141414',
    '--text-primary': 'rgba(255,255,255,0.85)',
    '--text-secondary': 'rgba(255,255,255,0.45)',
    '--disclaimer-bg': 'rgba(250,173,20,0.08)',
    '--disclaimer-border': 'rgba(250,173,20,0.2)',
  },
  light: {
    '--bg-base': '#f0f2f5',
    '--text-primary': 'rgba(0,0,0,0.88)',
    '--text-secondary': 'rgba(0,0,0,0.45)',
    '--disclaimer-bg': 'rgba(250,173,20,0.06)',
    '--disclaimer-border': 'rgba(250,173,20,0.15)',
  },
  compact: {
    '--bg-base': '#141414',
    '--text-primary': 'rgba(255,255,255,0.85)',
    '--text-secondary': 'rgba(255,255,255,0.45)',
    '--disclaimer-bg': 'rgba(250,173,20,0.08)',
    '--disclaimer-border': 'rgba(250,173,20,0.2)',
  },
  techblue: {
    '--bg-base': '#0a0e27',
    '--text-primary': '#e0e6ff',
    '--text-secondary': 'rgba(224,230,255,0.45)',
    '--disclaimer-bg': 'rgba(0,212,255,0.08)',
    '--disclaimer-border': 'rgba(0,212,255,0.2)',
  },
};
