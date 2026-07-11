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
