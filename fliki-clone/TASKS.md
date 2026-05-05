# Fliki Clone 开发任务清单

> 项目路径：`/Users/zhaoguangyuan/project/111/fliki-clone`
> 技术栈：Next.js 16 · TypeScript · Tailwind CSS 4 · shadcn/ui · Radix UI · Framer Motion · lucide-react
> 目标：复刻 Fliki (https://app.fliki.ai/) 类 AI 视频/配音 SaaS 产品，自有品牌化后可上线

---

## 完成标记说明
- `[ ]` 待开发
- `[x]` 已完成
- `[-]` 已跳过 / 不在当前范围

---

## 包 1：工程基础设施

- [x] T01 - 创建本任务文档 TASKS.md
- [x] T02 - 安装依赖：lucide-react · clsx · tailwind-merge · framer-motion · @radix-ui 系列
- [x] T03 - 设计 token：颜色/字体/圆角/间距/阴影写入 globals.css（对齐 Fliki 深色主题）
- [x] T04 - 基础组件：Button / Input / Badge / Card / Skeleton / Tabs / Avatar / Dialog / Dropdown

---

## 包 2：营销站

- [x] T05 - MarketingShell + Topnav（含 Logo、导航链接、登录/注册按钮）
- [x] T06 - Footer 组件
- [x] T07 - 首页 `/`：Hero + Feature + TemplateShowcase + HowItWorks + FAQ + FinalCTA
- [x] T08 - 定价页 `/pricing`：套餐卡片 + 功能对比表 + CTA

---

## 包 3：认证页

- [x] T09 - 登录页 `/login`
- [x] T10 - 注册页 `/signup`

---

## 包 4：AppShell（登录后壳层）

- [x] T11 - Sidebar 侧边栏（Dashboard / Projects / Templates / Create / Exports / Settings）
- [x] T12 - Topbar（搜索 / 通知 / 用户菜单 / 升级按钮）
- [x] T13 - AppShell 布局封装，供所有 /app/* 页面复用

---

## 包 5：项目中心

- [x] T14 - Dashboard 首页 `/app`（最近项目 + 快速开始 + 模板入口）
- [x] T15 - 文件列表页 `/app/files`（原 `/app/projects` 永久重定向至此；搜索 + 卡片网格 + 空态）
- [x] T16 - ProjectCard 组件（缩略图 / 名称 / 时间 / 更多菜单）

---

## 包 6：模板中心

- [x] T17 - 模板库页 `/app/templates`（分类导航 + 筛选 + 卡片网格）
- [x] T18 - TemplateCard 组件（预览图 / 时长 / 分类 / 使用按钮）

---

## 包 7：创建流程

- [x] T19 - 新建项目页 `/app/create`（脚本输入 + 模板选择 + 语言/语音配置）

---

## 包 8：创作工作台

- [x] T20 - 工作台壳层 `/app/project/[id]`（三栏布局：场景列表 + 预览区 + 属性面板）
- [x] T21 - 脚本/场景编辑面板
- [x] T22 - 预览区（视频占位 + 进度条 + 控制按钮）
- [x] T23 - 属性面板（声音 / 媒体 / 字幕配置）

---

## 包 9：生成与导出任务流

- [x] T24 - 生成按钮 + 任务状态机（idle / generating / success / error，见 `/app/project/[id]`）
- [x] T25 - Toast / Banner / Retry 反馈组件（`src/lib/feedback.ts` 封装 sonner，`src/components/ui/retry-banner.tsx`，已接入 `/app/project/[id]` 错误状态）
- [x] T26 - 导出页 `/app/project/[id]/export`（结果态 + 下载入口 + 跳转 Exports）
- [x] T26b - 导出列表 `/app/exports`

---

## 包 10：设置与计费

- [x] T27 - 个人设置页 `/settings/profile`
- [x] T28 - 订阅计划页 `/settings/billing`（当前计划 + 额度 + 升级弹窗）

---

## 包 11：App 内页（对齐 app.fliki.ai 抓取路由）

- [x] Files / Trash / Create 重定向、`/account`、Series、Playground、Voices、Assets、Characters、Brand kits、Team、Automation

---

## 里程碑

| 里程碑 | 验收路径 | 状态 |
|--------|----------|------|
| M1 营销站上线 | 访问首页 → 查看定价 → 点击注册 | 待验收 |
| M2 工作台主链路 | 注册 → 登录 → 查看项目 → 新建 → 进入工作台 | 待验收 |
| M3 生成闭环 | 输入脚本 → 点击生成 → 查看结果 → 导出 | 待验收 |

---

## Mock 数据接口桩

开发阶段用本地 mock JSON 驱动所有列表和详情页：
- `src/lib/mocks/projects.ts`
- `src/lib/mocks/templates.ts`
- `src/lib/mocks/user.ts`
