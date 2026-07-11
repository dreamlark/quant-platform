import { theme as antdTheme, type ThemeConfig } from 'antd';

// 暗色现代风主题（AntD darkAlgorithm）
export const darkTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: '#177ddc',
    colorBgBase: '#141414',
    borderRadius: 8,
    fontSize: 14,
  },
};

export const COLORS = {
  up: '#cf1322', // 涨（A 股红）
  down: '#3f8600', // 跌（A 股绿）
  factor: '#177ddc',
  tech: '#722ed1',
  sentiment: '#fa8c16',
  predict: '#13c2c2',
};
