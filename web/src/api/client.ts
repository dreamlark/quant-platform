import axios from 'axios';

// 调用 FastAPI（开发期经 vite 代理 /api）
export const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

export interface Signal {
  date: string;
  code: string;
  direction: number;
  confidence: number;
  source_tags: string;
  factor_contrib: number;
  tech_contrib: number;
  sentiment_contrib: number;
  predict_contrib: number;
}

export interface Sector {
  date: string;
  sector_code: string;
  sector_name: string;
  change_pct: number;
  rs: number;
  net_inflow: number;
  rotation_signal: string;
}

export interface FactorHealth {
  factor_name: string;
  date: string;
  ic: number;
  icir: number;
  rank_return: number;
  turnover: number;
  status: string;
  weight: number;
}

export interface WatchItem {
  code: string;
  name: string;
  cost_price: number;
  shares: number;
  current_price?: number;
  pnl_pct?: number;
  direction?: number;
  confidence?: number;
}

export interface SignalDetail {
  date: string;
  code: string;
  direction: number;
  confidence: number;
  source_tags: string;
  factor_contrib: number;
  tech_contrib: number;
  sentiment_contrib: number;
  predict_contrib: number;
  factor_detail: { factor_name: string; value: number }[];
  predict_detail: any[];
}

export interface DashboardSummary {
  date: string;
  market_temperature: number;
  brief?: string;
  top_signals: Signal[];
  sectors: Sector[];
  watchlist_alerts: WatchItem[];
}

// 运维控制：更新/调度状态
export interface UpdateStatus {
  status: 'idle' | 'running' | 'success' | 'failed';
  progress: number;        // 已完成步骤数
  total: number;           // 总步骤数
  current_step: string;    // 当前步骤名
  started_at: string | null;
  finished_at: string | null;
  last_success_date: string | null; // 最近成功更新的目标日
  last_error: string | null;
  message: string;
  auto_enabled: boolean;   // 自动运行是否开启
  next_run: string | null; // 下次自动运行时间
}

// —— 运维控制端点 ——
// 触发一轮数据更新与预测（异步；已在运行时返回 409）
export function triggerUpdate() {
  return api.post<{ status: string; message: string }>('/admin/update');
}

// 查询当前更新/调度状态
export function getUpdateStatus() {
  return api.get<UpdateStatus>('/admin/status');
}

// 开启 Web 可控的自动运行（工作日 18:30 自动更新）
export function startAuto() {
  return api.post<{ auto_enabled: boolean; next_run: string | null }>('/admin/auto/start');
}

// 关闭自动运行
export function stopAuto() {
  return api.post<{ auto_enabled: boolean }>('/admin/auto/stop');
}

// —— 运维监控（只读观测）——
export interface DataStatus {
  latest_date: string | null;
  days_since: number | null;
  is_stale: boolean;
  stock_count: number | null;
  universe_count: number | null;
  error?: string;
}

export interface FactorHealthSummary {
  latest_date: string | null;
  total: number;
  by_status: Record<string, number>;
  avg_icir: number | null;
  error?: string;
}

export interface ModelStatus {
  model_name: string;
  date: string;
  dir_acc: number | null;
  mape: number | null;
  coverage_count: number | null;
  error?: string;
}

export interface Freshness {
  signals_date: string | null;
  sector_date: string | null;
  brief_date: string | null;
  error?: string;
}

export interface MarketSentimentView {
  available: boolean;
  latest_date?: string | null;
  index_value?: number | null;
  sub_volume?: number | null;
  sub_price?: number | null;
  sub_money?: number | null;
  sub_valuation?: number | null;
  sub_riskpremium?: number | null;
  gsisi?: number | null;
  regime?: string | null;       // 恐惧 / 中性 / 贪婪
  thermometer?: number | null;
  signal?: string | null;       // 买入 / 半仓 / 空仓
  error?: string;
}

export interface RunRecord {
  run_id: string;
  trigger: string;
  started_at: string;
  finished_at: string;
  duration_sec: number;
  status: string;
  target_date: string | null;
  reached_step: string;
  progress: number;
  total: number;
  error: string | null;
}

export interface MonitorOverview {
  generated_at: string;
  data: DataStatus;
  factors: FactorHealthSummary;
  models: ModelStatus[];
  freshness: Freshness;
  market_sentiment?: MarketSentimentView;
  pipeline: UpdateStatus;
  last_run: RunRecord | null;
  auto: { enabled: boolean; next_run: string | null };
  history_count: number;
}

// 运维总览（数据状态 + 健康度 + 模型状态 + 实时管线 + 最近一次运行）
export function getMonitorOverview() {
  return api.get<MonitorOverview>('/monitor/overview');
}

// 运行历史记录
export function getMonitorHistory(limit = 50) {
  return api.get<{ runs: RunRecord[] }>('/monitor/history', { params: { limit } });
}
