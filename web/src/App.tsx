import { lazy, Suspense, useEffect } from 'react';
import { Layout, Menu, ConfigProvider, theme } from 'antd';
import {
  DashboardOutlined,
  FunctionOutlined,
  PieChartOutlined,
  LineChartOutlined,
  StarOutlined,
  MonitorOutlined,
  FundOutlined,
} from '@ant-design/icons';
import { Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom';
import { darkTheme } from './theme';
import { PageLoading } from './components/common';
import ErrorBoundary from './components/ErrorBoundary';

// 路由级代码分割：echarts 等重型依赖不进入首屏
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Factors = lazy(() => import('./pages/Factors'));
const Sectors = lazy(() => import('./pages/Sectors'));
const Stocks = lazy(() => import('./pages/Stocks'));
const Watchlist = lazy(() => import('./pages/Watchlist'));
const Monitor = lazy(() => import('./pages/Monitor'));

const { Sider, Content, Header } = Layout;

const DISCLAIMER =
  '【免责声明】本平台内容仅为量化分析信号与研究观点，不构成任何证券买卖建议。投资有风险，决策需谨慎。';

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '每日简报' },
  { key: '/factors', icon: <FunctionOutlined />, label: '因子' },
  { key: '/sectors', icon: <PieChartOutlined />, label: '板块' },
  { key: '/stocks', icon: <LineChartOutlined />, label: '股票' },
  { key: '/watchlist', icon: <StarOutlined />, label: '自选股' },
  { key: '/monitor', icon: <MonitorOutlined />, label: '运维监控' },
];

// 把 antd 暗色 token 注入到 :root CSS 变量，供 index.css 引用（替代硬编码颜色）
function RootStyle() {
  const { token } = theme.useToken();
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty('--app-color-bg-base', token.colorBgBase);
    root.style.setProperty('--app-color-warning', token.colorWarning);
    root.style.setProperty('--app-color-primary', token.colorPrimary);
    root.style.setProperty('--app-color-container', token.colorBgContainer);
    root.style.setProperty('--app-color-border', token.colorBorder);
  }, [token]);
  return null;
}

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const selected = menuItems.find((m) => location.pathname.startsWith(m.key))?.key || '/dashboard';

  return (
    <ConfigProvider theme={darkTheme}>
      <RootStyle />
      <Layout style={{ minHeight: '100vh' }}>
        <Sider theme="dark" breakpoint="lg" collapsedWidth={0} collapsible>
          <div className="app-logo">
            <span className="logo-mark">
              <FundOutlined />
            </span>
            <span>量化分析平台</span>
          </div>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[selected]}
            items={menuItems}
            onClick={(e) => navigate(e.key)}
          />
        </Sider>
        <Layout>
          <Header className="app-header">
            <span className="header-title">A 股日频量化分析平台</span>
            <span className="header-meta">analysis-first · 仅供研究参考</span>
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
                  <Route path="/monitor" element={<Monitor />} />
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
