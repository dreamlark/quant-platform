import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { COLORS } from '../theme';

export type { EChartsOption };

// 通用 ECharts 封装（暗色）
export function EChart({ option, height = 320 }: { option: EChartsOption; height?: number }) {
  return (
    <ReactECharts
      option={option}
      style={{ height }}
      notMerge
      lazyUpdate
      theme="dark"
    />
  );
}

// 统一坐标轴样式（取自主题语义色，保证与界面一致）
export const AXIS_STYLE = {
  axisLine: { lineStyle: { color: COLORS.axis } },
  axisLabel: { color: COLORS.axisLabel },
  axisTick: { lineStyle: { color: COLORS.axis } },
  splitLine: { lineStyle: { color: COLORS.grid } },
};

// 默认网格：containLabel 防止旋转后的类目标签被裁切
export const baseGrid = { left: 12, right: 24, top: 48, bottom: 28, containLabel: true };

// 暗色 tooltip 统一样式
export const tooltipStyle = {
  backgroundColor: 'rgba(15,18,22,0.92)',
  borderColor: 'rgba(255,255,255,0.12)',
  borderWidth: 1,
  textStyle: { color: 'rgba(255,255,255,0.88)', fontSize: 12 },
  extraCssText: 'backdrop-filter: blur(4px); border-radius: 8px;',
};

// 类目轴（含旋转与统一样式）
export function catAxis(data: string[], rotate = 0) {
  return {
    type: 'category' as const,
    data,
    ...AXIS_STYLE,
    axisLabel: { ...AXIS_STYLE.axisLabel, rotate, hideOverlap: true },
  };
}

// 数值轴（含名称与统一样式）
export function valAxis(name?: string) {
  return { type: 'value' as const, name, ...AXIS_STYLE };
}

export { COLORS };
