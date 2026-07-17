import { Progress, Typography } from 'antd';
import { COLORS } from './theme';

const { Text } = Typography;

// 更新/调度状态映射（Dashboard 与 Monitor 共用）
export const STATUS_META: Record<string, { color: string; label: string }> = {
  idle: { color: 'default', label: '空闲' },
  running: { color: 'processing', label: '更新中' },
  success: { color: 'success', label: '成功' },
  failed: { color: 'error', label: '失败' },
};

// 市场情绪温度计态 / 缩放态 / 信号态 颜色映射
export const REGIME_COLOR: Record<string, string> = {
  恐惧: 'red',
  中性: 'default',
  贪婪: 'green',
};

export const REGIME_STATE_COLOR: Record<string, string> = {
  bull: 'green',
  neutral: 'default',
  bear: 'orange',
  panic: 'red',
};

export const SIGNAL_COLOR: Record<string, string> = {
  买入: 'green',
  半仓: 'gold',
  空仓: 'red',
};

// 因子健康度状态颜色
export const FACTOR_STATUS_COLOR: Record<string, string> = {
  有效: 'green',
  衰减: 'gold',
  失效: 'red',
};

// 批处理运行步骤颜色
export const BATCH_STEP_COLOR: Record<string, string> = {
  ok: 'green',
  fail: 'red',
};

// 情绪分项子进度条（量能/价格/资金/估值/风险溢价）
export function subBar(label: string, v: number | null | undefined) {
  if (v == null) return null;
  return (
    <div style={{ marginTop: 4 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>{label}：{v.toFixed(1)}</Text>
      <Progress
        percent={Math.round(v)}
        size="small"
        showInfo={false}
        strokeColor={v >= 50 ? COLORS.up : COLORS.down}
      />
    </div>
  );
}
