import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import * as echarts from 'echarts/core';
import { COLORS, TOKENS } from '../theme';

export type { EChartsOption };

// ══════════════════════════════════════════
//  Custom ECharts Theme: "quant-dark"
//  Replaces generic "dark" theme with brand-aligned tokens
// ══════════════════════════════════════════

/** Register our custom theme at module load time */
const quantDarkTheme: Record<string, unknown> = {
  color: [
    TOKENS.accent,      // 0: primary accent (teal)
    TOKENS.factor,      // 1: factor (sky blue)
    TOKENS.tech,        // 2: tech (purple)
    TOKENS.sentiment,   // 3: sentiment (orange)
    TOKENS.predict,     // 4: predict (lavender)
    TOKENS.up,          // 5: up/bullish (red)
    TOKENS.down,        // 6: down/bearish (green)
    TOKENS.warning,     // 7: warning (amber)
    '#f472b6',          // 9: pink
    '#a3e635',          //10: lime
  ],

  backgroundColor: 'transparent',

  // Title
  title: {
    textStyle: {
      color: TOKENS.textPrimary,
      fontFamily: "'Outfit', -apple-system, sans-serif",
      fontWeight: 600,
      fontSize: 14,
    },
    subtextStyle: {
      color: TOKENS.textTertiary,
      fontSize: 11.5,
      fontFamily: "'JetBrains Mono', monospace",
    },
  },

  // Legend
  legend: {
    textStyle: {
      color: TOKENS.textSecondary,
      fontSize: 12,
      fontFamily: "'Outfit', -apple-system, sans-serif",
    },
    iconColor: undefined, // let each series set its own
    itemWidth: 16,
    itemHeight: 8,
    borderRadius: 4,
    top: 4,
    right: 0,
    padding: [0, 12, 0, 0],
  },

  // Tooltip
  tooltip: {
    backgroundColor: `rgba(17,22,32,0.94)`,
    borderColor: `${TOKENS.borderStrong}`,
    borderWidth: 1,
    borderRadius: 10,
    padding: [10, 14],
    extraCssText:
      'backdrop-filter: blur(12px) saturate(1.4);' +
      '-webkit-backdrop-filter: blur(12px) saturate(1.4);' +
      'box-shadow: 0 8px 28px rgba(0,0,0,0.45);',
    textStyle: {
      color: TOKENS.textPrimary,
      fontSize: 12.5,
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    },
    axisPointer: {
      lineStyle: {
        color: TOKENS.borderStrong,
        width: 1,
        type: 'solid' as const,
      },
      shadowStyle: {
        color: 'rgba(0,0,0,0.25)',
      },
    },
  },

  // Grid
  grid: {
    left: 14,
    right: 24,
    top: 48,
    bottom: 30,
    containLabel: true,
  },

  // Category Axis
  xAxis: {
    axisLine: { lineStyle: { color: COLORS.axis } },
    axisTick: { lineStyle: { color: COLORS.axis }, alignWithLabel: true },
    axisLabel: {
      color: COLORS.axisLabel,
      fontSize: 11.5,
      fontFamily: "'JetBrains Mono', monospace",
      letterSpacing: "0.01em",
    },
    splitLine: { show: false },
  },

  // Value Axis
  yAxis: {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: COLORS.axisLabel,
      fontSize: 11.5,
      fontFamily: "'JetBrains Mono', monospace",
      letterSpacing: "0.01em",
      fontVariantNumeric: "tabular-nums",
    },
    splitLine: {
      lineStyle: {
        color: COLORS.grid,
        type: 'dashed' as const,
        dashOffset: 4,
      },
    },
  },

  // Data Zoom
  dataZoom: {
    dataBackground: {
      areaStyle: { color: TOKENS.accentMuted },
      lineStyle: { color: TOKENS.accent },
    },
    fillerColor: `${TOKENS.accentMuted}`,
    borderColor: TOKENS.borderStrong,
    handleStyle: { color: TOKENS.accent },
    textStyle: { color: TOKENS.textSecondary, fontSize: 11 },
  },

  // Visual Map
  visualMap: {
    textStyle: { color: TOKENS.textSecondary, fontSize: 11 },
  },

  // Timeline
  timeline: {
    lineStyle: { color: TOKENS.border },
    itemStyle: { color: TOKENS.borderStrong, borderColor: TOKENS.bgElevated },
    controlStyle: { color: TOKENS.borderStrong, borderColor: TOKENS.bgElevated },
    label: { color: TOKENS.textSecondary, fontSize: 11 },
    emphasis: {
      itemStyle: { color: TOKENS.accent },
      controlStyle: { color: TOKENS.accent },
      label: { color: TOKENS.textPrimary },
    },
  },
};

// Register the custom theme
echarts.registerTheme('quant-dark', quantDarkTheme);


// ══════════════════════════════════════════
//  EChart Wrapper Component
//  Uses "quant-dark" theme by default
// ══════════════════════════════════════════

export function EChart({ option, height = 320 }: { option: EChartsOption; height?: number }) {
  return (
    <ReactECharts
      option={option}
      style={{ height }}
      notMerge
      lazyUpdate
      theme="quant-dark"
      opts={{ renderer: 'canvas' }}
    />
  );
}


// ══════════════════════════════════════════
//  Axis Helpers (consistent styling across charts)
// ══════════════════════════════════════════

/** Unified axis style tokens */
export const AXIS_STYLE = {
  axisLine: { lineStyle: { color: COLORS.axis, width: 1 } },
  axisLabel: {
    color: COLORS.axisLabel,
    fontSize: 11.5,
    fontFamily: "'JetBrains Mono', monospace",
    letterSpacing: "0.01em",
  },
  axisTick: { lineStyle: { color: COLORS.axis }, alignWithLabel: true },
  splitLine: {
    lineStyle: {
      color: COLORS.grid,
      type: 'dashed' as const,
      dashOffset: 4,
    },
  },
};

/** Default grid config with containLabel to prevent label clipping */
export const baseGrid = { left: 14, right: 24, top: 48, bottom: 30, containLabel: true };

/** Refined glassmorphism tooltip style */
export const tooltipStyle = {
  backgroundColor: 'rgba(15,19,26,0.94)',
  borderColor: 'rgba(255,255,255,0.10)',
  borderWidth: 1,
  borderRadius: 10,
  padding: [10, 14] as [number, number],
  textStyle: {
    color: 'rgba(255,255,255,0.90)',
    fontSize: 12.5,
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  },
  extraCssText:
    'backdrop-filter: blur(12px) saturate(1.4); ' +
    '-webkit-backdrop-filter: blur(12px) saturate(1.4); ' +
    'box-shadow: 0 8px 28px rgba(0,0,0,0.40); ' +
    'border-radius: 10px;',
};

/**
 * Category axis helper with rotation support.
 * Uses unified AXIS_STYLE for consistency.
 */
export function catAxis(data: string[], rotate = 0) {
  return {
    type: 'category' as const,
    data,
    ...AXIS_STYLE,
    axisLabel: {
      ...AXIS_STYLE.axisLabel,
      rotate,
      hideOverlap: true,
    },
  };
}

/**
 * Value axis helper with optional name.
 * Uses unified AXIS_STYLE for consistency.
 */
export function valAxis(name?: string) {
  return {
    type: 'value' as const,
    name,
    nameTextStyle: {
      color: COLORS.axisLabel,
      fontSize: 11.5,
      fontFamily: "'JetBrains Mono', monospace",
      padding: [0, 0, 0, 8],
    },
    ...AXIS_STYLE,
  };
}


// ══════════════════════════════════════════
//  Chart Color Palettes (for bar/line/pie series)
// ══════════════════════════════════════════

/** Semantic palette for stock-market charts */
export const MARKET_PALETTE = {
  up: TOKENS.up,
  down: TOKENS.down,
  upBg: TOKENS.upBg,
  downBg: TOKENS.downBg,
  accent: TOKENS.accent,
  factor: TOKENS.factor,
  tech: TOKENS.tech,
  sentiment: TOKENS.sentiment,
};

/** Gradient fills for bars */
export function barGradient(colors: string[]) {
  return {
    type: 'linear' as const,
    x: 0, y: 0, x2: 0, y2: 1,
    colorStops: colors.map((c, i) => ({
      offset: i / (colors.length - 1),
      color: c,
    })),
  };
}

export { COLORS };
