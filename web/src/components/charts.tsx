import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';

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

const AXIS_STYLE = {
  axisLine: { lineStyle: { color: 'rgba(255,255,255,0.25)' } },
  axisLabel: { color: 'rgba(255,255,255,0.65)' },
  splitLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
};

export const baseGrid = { left: 50, right: 24, top: 40, bottom: 40 };

export { AXIS_STYLE };
