import React from 'react';
import { Layout, Menu, ConfigProvider, Typography } from 'antd';
import {
  DashboardOutlined,
  FunctionOutlined,
  PieChartOutlined,
  LineChartOutlined,
  StarOutlined,
} from '@ant-design/icons';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { darkTheme } from './theme';
import Dashboard from './pages/Dashboard';
import Factors from './pages/Factors';
import Sectors from './pages/Sectors';
import Stocks from './pages/Stocks';
import Watchlist from './pages/Watchlist';

const { Sider, Content, Header } = Layout;

const DISCLAIMER =
  '【免责声明】本平台内容仅为量化分析信号与研究观点，不构成任何证券买卖建议。投资有风险，决策需谨慎。';

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '每日简报' },
  { key: '/factors', icon: <FunctionOutlined />, label: '因子' },
  { key: '/sectors', icon: <PieChartOutlined />, label: '板块' },
  { key: '/stocks', icon: <LineChartOutlined />, label: '股票' },
  { key: '/watchlist', icon: <StarOutlined />, label: '自选股' },
];

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const selected = menuItems.find((m) => location.pathname.startsWith(m.key))?.key || '/dashboard';

  return (
    <ConfigProvider theme={darkTheme}>
      <Layout style={{ minHeight: '100vh' }}>
        <Sider theme="dark" breakpoint="lg" collapsible>
          <div className="app-logo">量化分析平台</div>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[selected]}
            items={menuItems}
            onClick={(e) => navigate(e.key)}
          />
        </Sider>
        <Layout>
          <div className="disclaimer">{DISCLAIMER}</div>
          <Content>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/factors" element={<Factors />} />
              <Route path="/sectors" element={<Sectors />} />
              <Route path="/stocks" element={<Stocks />} />
              <Route path="/watchlist" element={<Watchlist />} />
            </Routes>
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}
