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

// 统一请求封装：返回 data；出错时抛出异常（不再静默吞掉），由调用方 .catch 处理
export function apiGet<T>(url: string, config?: import('axios').AxiosRequestConfig): Promise<T> {
  return api.get<T>(url, config).then((r) => r.data);
}

// 把未知错误收敛为可读中文文案
export function errMsg(e: unknown): string {
  if (axios.isAxiosError(e)) {
    if (e.response) {
      const data = e.response.data;
      const detail = typeof data === 'string' ? data : JSON.stringify(data);
      return `请求失败（${e.response.status}）：${detail}`.slice(0, 200);
    }
    if (e.request) return '网络异常：无法连接服务';
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return '未知错误';
}

// 是否触发了「已有更新在运行」的冲突（HTTP 409）
export function isAxiosConflict(e: unknown): boolean {
  return axios.isAxiosError(e) && e.response?.status === 409;
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
  predict_detail: Record<string, unknown>[];
}

export interface DashboardSummary {
  date: string;
  market_latest_date?: string | null;  // 行情库最新交易日
  market_temperature: number;
  brief?: string;
  top_signals: Signal[];
  sectors: Sector[];
  watchlist_alerts: WatchItem[];
  market_sentiment?: MarketSentimentView;
}

// 运维控制：更新/调度状态
export interface UpdateStatus {
  status: 'idle' | 'running' | 'success' | 'failed';
  progress: number;        // 已完成步骤数
  total: number;           // 总步骤数
  current_step: string;    // 当前步骤名
  step_started_at: string | null;  // 当前步骤开始时间（卡死检测用）
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

// 实时运行日志（含每步状态/进度）
export function getRunLogs() {
  return api.get<{ logs: RunLog[]; status: string }>('/admin/logs');
}

// 运行日志条目
export interface RunLog {
  ts: string;
  level: 'info' | 'success' | 'warn' | 'error';
  step: string;
  step_label: string;
  message: string;
}

// 开启 Web 可控的自动运行（工作日指定时间自动更新，默认 18:30）
interface AutoStartResult {
  auto_enabled: boolean;
  next_run: string | null;
  schedule_time: string;
}
export function startAuto(hour?: number, minute?: number) {
  const params = new URLSearchParams();
  if (hour != null) params.append('hour', String(hour));
  if (minute != null) params.append('minute', String(minute));
  const qs = params.toString() ? `?${params}` : '';
  return api.post<AutoStartResult>(`/admin/auto/start${qs}`);
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
  regime?: string | null;       // 恐惧 / 中性 / 贪婪（温度计情绪态）
  regime_state?: string | null; // bull / neutral / bear / panic（缩放用）
  regime_scale?: number | null; // 当前 regime_state 对应的置信度缩放系数
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

// 批处理运行逐步状态（P3-1 落盘）
export interface BatchRunStepSummary {
  step: string;
  status: string; // ok | fail
  duration_s: number;
}
export interface BatchRunRecord {
  kind: string;
  run_id: string;
  date: string;
  trigger: string;
  status: string;
  start_ts: string;
  end_ts: string;
  duration_s: number;
  error: string | null;
  steps: BatchRunStepSummary[];
}
export interface BatchRunStepDetail {
  run_id: string;
  step: string;
  status: string;
  ts: string;
  duration_s: number;
  error: string | null;
}
export interface BatchRun {
  run: BatchRunRecord | null;
  steps: BatchRunStepDetail[];
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
  batch_run: BatchRun;
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

// —— 热点语义分析 ——
export interface HotspotItem {
  ts: string;
  source: string;
  title: string;
  topic: string;
  sentiment: string;
  sentiment_score: number;
  impact: string;
  impact_score: number;
  related_sectors: string;
  related_codes: string;
  reasoning: string;
  composite_score: number;
}

export interface HotspotDigest {
  date: string;
  content: string;
  total_count: number;
  positive: number;
  negative: number;
  neutral: number;
}

export function getHotspotLatest(limit = 50, date?: string) {
  return api.get<{ items: HotspotItem[]; total: number }>('/hotspot/latest', {
    params: { limit, ...(date ? { date } : {}) },
  });
}

export function getHotspotByCode(code: string, days = 7) {
  return api.get<{ items: HotspotItem[]; total: number }>(`/hotspot/by-code/${code}`, {
    params: { days },
  });
}

export function getHotspotDigest(date?: string) {
  return api.get<HotspotDigest>('/hotspot/digest', {
    params: date ? { date } : {},
  });
}

export function getHotspotStats(days = 14) {
  return api.get<{ daily_stats: any[]; total: number }>('/hotspot/stats', {
    params: { days },
  });
}

// —— 系统设置 ——
export interface LLMSettingsView {
  provider: string;
  model: string;
  base_url: string;
  api_key_masked: string;
  api_key_env: string;
  temperature: number;
  max_tokens: number;
  cache_enabled: boolean;
  is_configured: boolean;
}

export interface PathSettingsView {
  data_dir: string;
  market_db: string;
  analytics_db: string;
  raw_cache: string;
}

export interface SchedulerSettingsView {
  enabled: boolean;
  cron: string;
  timezone: string;
}

export interface HotspotSettingsView {
  enabled: boolean;
  batch_size: number;
  daemon_interval: number;
  simhash_threshold: number;
}

export interface FusionSettingsView {
  hotspot_alpha: number;
  regime_adjust_enabled: boolean;
}

export interface UIPreferences {
  theme?: string;
  chart_up_color?: string;
  language?: string;
}

export interface SettingsView {
  llm: LLMSettingsView;
  paths: PathSettingsView;
  scheduler: SchedulerSettingsView;
  hotspot: HotspotSettingsView;
  fusion: FusionSettingsView;
  ui: UIPreferences;
  app: Record<string, any>;
}

export interface SettingsPatch {
  llm?: Partial<LLMSettingsView & { api_key: string }>;
  paths?: Partial<PathSettingsView>;
  scheduler?: Partial<SchedulerSettingsView>;
  hotspot?: Partial<HotspotSettingsView>;
  fusion?: Partial<FusionSettingsView>;
  ui?: Partial<UIPreferences>;
}

export interface PathInfo {
  configured: string;
  absolute: string;
  exists: boolean;
  size_mb?: number | null;
}

export function getSettings() {
  return api.get<SettingsView>('/settings');
}

export function updateSettings(patch: SettingsPatch) {
  return api.put<{ status: string; changed_sections: string[]; message: string }>('/settings', patch);
}

export function testLLM() {
  return api.post<{ success: boolean; message: string; latency_ms?: number; usage?: any }>('/settings/llm/test');
}

export function getPathsInfo() {
  return api.get<Record<string, PathInfo>>('/settings/paths/info');
}

export function migratePaths(newDataDir: string) {
  return api.post<{ status: string; moved: any[]; new_data_dir: string; message: string }>(
    '/settings/paths/migrate',
    null,
    { params: { new_data_dir: newDataDir } }
  );
}
