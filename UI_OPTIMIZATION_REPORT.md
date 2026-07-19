# quant-platform 前端 UI 优化报告（基于最新代码 3138bd6）

> 项目：`web/`（React 18 + TypeScript + Ant Design 5 + ECharts，暗色主题）
> 背景：在 `origin/master @ 3138bd6` 之上叠加 UI 优化。**完整保留**了该提交已采纳的健壮性改造：
> - `constants.tsx`：状态/颜色映射与 `subBar` 去重
> - `api/client.ts`：`apiGet` / `errMsg` / `isAxiosConflict` 错误处理封装
> - `App.tsx` 的 `RootStyle`（antd token 注入 CSS 变量）
> - 各页面既有的错误 `Alert` 展示与数据兼容逻辑
>
> 目标：在不改动任何后端 API 契约、不破坏既有健壮性的前提下，提升视觉一致性、可用性与可维护性。
> 验证：`npm install` → `npm run build`（tsc 类型检查 + vite 打包）**零错误通过**；`vite preview` + 无头 Chromium 截图 7 张全部成功（见 `shots/`）。

---

## 一、本轮新增的 UI 优化

| # | 类别 | 改动 | 位置 |
|---|------|------|------|
| 1 | 主题纵深 | 重构为三级明度令牌——基底 `#0e1116` → 卡片 `#171b22` → 浮层 `#1f242d`，制造明确纵深；统一圆角/控件高度/边框与表格 hover | `src/theme.ts` |
| 2 | 缺失布局 | 补全顶部 `Header`（品牌渐变标识 + 研究标记），注入 `app-header` 玻璃拟态样式 | `src/App.tsx` / `src/index.css` |
| 3 | 健壮性边界 | 新增全局 `ErrorBoundary`（避免单页异常整站白屏）+ 404 兜底路由 | `src/components/ErrorBoundary.tsx` / `src/App.tsx` |
| 4 | 首屏性能 | 路由级 `React.lazy` + `Suspense`，echarts 不进首屏；构建产物按 react/antd/echarts 分包 | `src/App.tsx` / `vite.config.ts` |
| 5 | 加载体验 | 裸 `<Spin/>` 全部升级为 `Skeleton` 骨架屏（`PageLoading`） | `src/components/common.tsx` + 各页面 |
| 6 | 共享组件 | 新增 `common.tsx`：`PageHeader` / `PageLoading` / `EmptyHint` / `StatusTag` / `dirTag` / `SentimentCard`，消除 Dashboard 与 Monitor 重复的「情绪卡」大段逻辑 | `src/components/common.tsx` |
| 7 | 响应式 | 所有 `Col` 写死 `span` 改为 `xs/sm/md/lg` 断点；表格加 `scroll.x` | 各页面 |
| 8 | 图表封装 | `baseGrid` 默认 `containLabel` 防标签裁切；新增 `catAxis()` / `valAxis()` / `tooltipStyle()` 与暗色毛玻璃 tooltip；各图表补 `legend` | `src/components/charts.tsx` + 各页面 |
| 9 | 温度计着色 | 新增 `tempColor()` 给市场温度计按分档（红/橙/黄/绿）着色 | `src/theme.ts` + `Dashboard.tsx` |
| 10 | 组件 bug | `Factors`/`Sectors` 的 `DatePicker` 由非受控 `defaultValue` 改为受控 `value` + `allowClear`（修复清空/回显失效） | `src/pages/Factors.tsx` / `Sectors.tsx` |
| 11 | 组件 bug | `Stocks` 的 `AutoComplete` 增加 `value` + `onChange`，深链时搜索框正确回显选中标的 | `src/pages/Stocks.tsx` |
| 12 | 工程化 | `index.html` 补充 SVG favicon、`meta description` / `theme-color` / OG 标签 | `web/index.html` |
| 13 | 样式 | `index.css` 补充品牌标识、Header、统一页头、加载态、暗色滚动条与窄屏媒体查询 | `src/index.css` |

---

## 二、改动文件清单

| 文件 | 性质 |
|------|------|
| `src/theme.ts` | 重写：三级明度令牌 + `tempColor` |
| `src/index.css` | 重写：品牌/Header/页头/加载态/滚动条 |
| `src/App.tsx` | 加 Header / `ErrorBoundary` / `lazy` / 404 / `RootStyle` 扩展 |
| `src/components/common.tsx` | **新增**：共享 UI 组件 |
| `src/components/ErrorBoundary.tsx` | **新增**：全局错误边界 |
| `src/components/charts.tsx` | 重写：语义化坐标轴 + `containLabel` + 辅助函数 |
| `src/pages/Dashboard.tsx` | 响应式 + 骨架屏 + 温度计着色 + 复用 `SentimentCard` |
| `src/pages/Monitor.tsx` | 响应式 + 骨架屏 + 复用 `SentimentCard` / `StatusTag` |
| `src/pages/Factors.tsx` | DatePicker 受控 + 图表封装 + 图例 |
| `src/pages/Sectors.tsx` | DatePicker 受控 + 图表封装 + 图例 |
| `src/pages/Stocks.tsx` | AutoComplete 回显 + 响应式 + 图表封装 |
| `src/pages/Watchlist.tsx` | 复用 `dirTag` + 统一页头 + 骨架屏 |
| `vite.config.ts` | vendor 分包 + preview 代理 |
| `web/index.html` | favicon + 元信息 |

---

## 三、提交与推送说明

- 本分支当前 `HEAD = origin/master (3138bd6)`，优化以**一个快进提交**叠加在其上，**不存在覆盖你已上传代码的风险**（普通 `git push` 为 fast-forward；`--force` 绝不使用）。
- 沙箱无 GitHub 写权限凭证，需你提供 **Personal Access Token**（仓库 `repo` 范围）后由我执行 `git push`；或你自行 `git push origin master`。

---

## 四、可选后续建议（未实施）

1. **骨架屏细化**：`PageLoading` 可改为按页面结构定制（如 Dashboard 预置温度/信号表占位）。
2. **图表懒加载**：当前按路由分包已瘦身首屏；若进一步，可对非首屏重型图表做 `React.lazy`。
3. **明/暗主题切换**：当前仅暗色（品牌偏暗），如需可加 `ConfigProvider` 切换。
4. **情绪分项语义**：`subBar` 当前红=高/绿=低（沿用仓库约定），如需「绿=强/红=弱」可改为 `v>=50 ? COLORS.down : COLORS.up`。
