import React, { lazy, Suspense, useState, useEffect } from 'react';
import { Layout, Menu, ConfigProvider, Typography, Button, Tooltip } from 'antd';
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
import { darkTheme, getTheme, type ThemeMode, themeCSSVars } from './theme';
import { PageLoading } from './components/common';
import ErrorBoundary from './components/ErrorBoundary';

// 路由级代码分割：echarts 等重型依赖不进入首屏
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Factors = lazy(() => import('./pages/Factors'));
const Sectors = lazy(() => import('./pages/Sectors'));
const Stocks = lazy(() => import('./pages/Stocks'));
const Watchlist = lazy(() => import('./pages/Watchlist'));
const Monitor = lazy(() => import('./pages/Monitor'));
const DataManagement = lazy(() => import('./pages/Data'));
// Settings / Hotspot 不做懒加载（首屏即可能访问，且体积小）
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

  // 主题状态（支持 dark/light/compact/techblue）
  const [themeMode, setThemeMode] = useState<ThemeMode>('dark');

  // 从 localStorage 初始化
  useEffect(() => {
    const saved = localStorage.getItem('theme-mode') as ThemeMode;
    if (saved && ['dark', 'light', 'compact', 'techblue'].includes(saved)) {
      setThemeMode(saved);
    }
  }, []);

  // 监听设置页面的主题切换事件
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

  // 应用主题 CSS 变量
  useEffect(() => {
    const vars = themeCSSVars[themeMode] || themeCSSVars.dark;
    const root = document.documentElement;
    Object.entries(vars).forEach(([k, v]) => {
      root.style.setProperty(k, v);
    });
    root.style.setProperty('--app-color-bg-base', vars['--bg-base'] || '#141414');
  }, [themeMode]);

  const currentTheme = getTheme(themeMode);

  return (
    <ConfigProvider theme={currentTheme}>
      <Layout style={{ minHeight: '100vh' }}>
        <Sider theme={themeMode === 'light' ? 'light' : 'dark'} breakpoint="lg" collapsedWidth={0} collapsible>
          <div className="app-logo">
            <span className="logo-mark"><FundOutlined /></span>
            <span>量化分析平台</span>
          </div>
          <Menu
            theme={themeMode === 'light' ? 'light' : 'dark'}
            mode="inline"
            selectedKeys={[selected]}
            items={menuItems}
            onClick={(e) => navigate(e.key)}
          />
        </Sider>
        <Layout>
          <Header
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '0 16px',
              height: 48,
              background: themeMode === 'light' ? '#fff' : '#1f1f1f',
              borderBottom: '1px solid rgba(128,128,128,0.15)',
            }}
          >
            <span style={{
              fontSize: 14,
              color: themeMode === 'light' ? 'rgba(0,0,0,0.88)' : 'rgba(255,255,255,0.88)',
              fontWeight: 600,
            }}>
              A 股日频量化分析平台
            </span>
            <Tooltip title="系统设置">
              <Button
                type="text"
                icon={<SettingOutlined />}
                onClick={() => navigate('/settings')}
                style={{
                  fontSize: 16,
                  color: themeMode === 'light' ? '#333' : 'rgba(255,255,255,0.65)',
                }}
              />
            </Tooltip>
          </Header>
          <div className="disclaimer">{DISCLAIMER}</div>
          <Content>
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
