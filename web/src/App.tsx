import React, { lazy, Suspense, useState, useEffect } from 'react';
import { Layout, Menu, ConfigProvider, Button, Tooltip } from 'antd';
import {
  DashboardOutlined,
  FunctionOutlined,
  PieChartOutlined,
  LineChartOutlined,
  StarOutlined,
  MonitorOutlined,
  DatabaseOutlined,
  FireOutlined,
  SettingOutlined,
  FundOutlined,
} from '@ant-design/icons';
import { Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom';
import { getTheme, type ThemeMode, themeCSSVars } from './theme';
import { PageLoading } from './components/common';
import ErrorBoundary from './components/ErrorBoundary';

// Route-level code splitting: heavy deps (echarts) excluded from initial bundle
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Factors = lazy(() => import('./pages/Factors'));
const Sectors = lazy(() => import('./pages/Sectors'));
const Stocks = lazy(() => import('./pages/Stocks'));
const Watchlist = lazy(() => import('./pages/Watchlist'));
const Monitor = lazy(() => import('./pages/Monitor'));
const DataManagement = lazy(() => import('./pages/Data'));
// Settings / Hotspot: small footprint, no lazy needed
import Hotspot from './pages/Hotspot';
import Settings from './pages/Settings';

const { Sider, Content, Header } = Layout;

const DISCLAIMER =
  '【免责声明】本平台内容仅为量化分析信号与研究观点，不构成任何证券买卖建议。投资有风险，决策需谨慎。';

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '每日简报' },
  { key: '/factors', icon: <FunctionOutlined />, label: '因子' },
  { key: '/sectors', icon: <PieChartOutlined />, label: '板块' },
  { key: '/stocks', icon: <LineChartOutlined />, label: '股票' },
  { key: '/watchlist', icon: <StarOutlined />, label: '自选股' },
  { key: '/hotspot', icon: <FireOutlined />, label: '热点分析' },
  { key: '/monitor', icon: <MonitorOutlined />, label: '运维监控' },
  { key: '/data', icon: <DatabaseOutlined />, label: '数据管理' },
];

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const selected = menuItems.find((m) => location.pathname.startsWith(m.key))?.key || '/dashboard';

  // Theme state (dark / light / compact / techblue)
  const [themeMode, setThemeMode] = useState<ThemeMode>('dark');

  // Initialize from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('theme-mode') as ThemeMode;
    if (saved && ['dark', 'light', 'compact', 'techblue'].includes(saved)) {
      setThemeMode(saved);
    }
  }, []);

  // Listen for theme-switch events from Settings page
  useEffect(() => {
    const handler = (e: Event) => {
      const mode = (e as CustomEvent).detail as ThemeMode;
      if (['dark', 'light', 'compact', 'techblue'].includes(mode)) {
        setThemeMode(mode);
        localStorage.setItem('theme-mode', mode);
      }
    };
    window.addEventListener('theme-change', handler);
    return () => window.removeEventListener('theme-change', handler);
  }, []);

  // Apply CSS custom properties for non-AntD elements
  useEffect(() => {
    const vars = themeCSSVars[themeMode] || themeCSSVars.dark;
    const root = document.documentElement;
    Object.entries(vars).forEach(([k, v]) => {
      root.style.setProperty(k, v);
    });
  }, [themeMode]);

  const currentTheme = getTheme(themeMode);

  // Resolve header background based on theme
  const isDark = themeMode !== 'light';
  const headerStyle: React.CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '0 22px',
    height: 54,
    position: 'relative',
    zIndex: 10,
    background: 'transparent',
    borderBottom: 'none',
  };

  return (
    <ConfigProvider theme={currentTheme}>
      <Layout style={{ minHeight: '100vh', background: 'var(--bg-base)' }}>
        {/* ── Sidebar ── */}
        <Sider
          theme={isDark ? 'dark' : 'light'}
          breakpoint="lg"
          collapsedWidth={48}
          collapsible
          style={{
            background: 'var(--bg-sidebar)',
            borderRight: '1px solid var(--border)',
          }}
          width={218}
        >
          <div className="app-logo">
            <span className="logo-mark"><FundOutlined /></span>
            <span>量化分析平台</span>
          </div>
          <Menu
            theme={isDark ? 'dark' : 'light'}
            mode="inline"
            selectedKeys={[selected]}
            items={menuItems}
            onClick={(e) => navigate(e.key)}
            style={{
              borderInlineEnd: 'none',
              background: 'transparent',
            }}
          />
        </Sider>

        {/* ── Main Area ── */}
        <Layout style={{ background: 'var(--bg-base)' }}>
          {/* Glassmorphism Header */}
          <Header style={headerStyle} className="app-header">
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
              <span className="header-title">A 股日频量化分析平台</span>
              <span
                className="header-meta"
                style={{
                  fontSize: 11,
                  color: isDark ? 'var(--text-tertiary)' : 'rgba(0,0,0,0.35)',
                }}
              >
                analysis-first · 仅供研究参考
              </span>
            </div>

            <Tooltip title="系统设置">
              <Button
                type="text"
                icon={<SettingOutlined />}
                onClick={() => navigate('/settings')}
                style={{
                  fontSize: 16,
                  color: isDark ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.5)',
                  borderRadius: 'var(--radius-sm)',
                  transition: 'all var(--transition-fast)',
                }}
              />
            </Tooltip>
          </Header>

          {/* Disclaimer Bar */}
          <div className="disclaimer">{DISCLAIMER}</div>

          {/* Page Content */}
          <Content style={{ background: 'transparent' }}>
            <ErrorBoundary>
              <Suspense fallback={<PageLoading tip="页面加载中…" />}>
                <Routes>
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/factors" element={<Factors />} />
                  <Route path="/sectors" element={<Sectors />} />
                  <Route path="/stocks" element={<Stocks />} />
                  <Route path="/stocks/:code" element={<Stocks />} />
                  <Route path="/watchlist" element={<Watchlist />} />
                  <Route path="/hotspot" element={<Hotspot />} />
                  <Route path="/monitor" element={<Monitor />} />
                  <Route path="/data" element={<DataManagement />} />
                  <Route path="/settings" element={<Settings />} />
                  <Route path="*" element={<Navigate to="/dashboard" replace />} />
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}
