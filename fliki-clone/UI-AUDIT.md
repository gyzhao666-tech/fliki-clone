# UI 自检报告（基于 cursor-ide-browser 截图）

> 生成方法：`cursor-ide-browser` 打开 `/zh/app/files` → 对照 `.cursor/rules/ui-design-system.mdc` 与 `component-patterns.mdc` 自检。
> 截图样本：侧边栏 360px 视口（side panel 模式）。

## 高严重度（阻塞体验）

- [ ] **A1 · i18n 严重不一致**：左侧 sidebar 全中文，但 `What's new` 抽屉（标题、日期、所有长文）100% 英文硬编码。违反 `component-patterns.mdc` 的"禁止硬编码中英文字符串"。
  - 涉及文件：`src/components/app-shell/whats-new.tsx` 或类似命名
  - 修复方案：把所有长文抽到 `messages/{locale}.json` 的 `whatsNew` 命名空间

- [ ] **A2 · What's new 抽屉首次访问自动展开**：用户进 `/app/files` 主目的是看文件，What's new 直接占满半屏阻挡主列表
  - 修复方案：默认收起，仅当用户主动点 What's new 按钮 / 有真正的新版本未读时弹出
  - 增加 `localStorage` 标记已读

## 中严重度（体验/视觉细节）

- [ ] **B1 · 底部"设置"按钮被升级卡片遮挡**：升级卡片绝对定位/高度过高，盖住了"设置"链接的上半部分
  - 修复方案：要么把升级卡片改成普通流式块，要么给 sidebar 底部加 padding-bottom 等于卡片高度

- [ ] **B2 · "资源" 分组 label 对比度过低**：颜色比 `--text-muted` 还淡，疑似硬编码 `opacity-50` 或自定义颜色
  - 修复方案：统一改成 `text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]`（与现有"Scenes" label 对齐）

## 低严重度（一致性）

- [ ] **C1 · 顶部通知 bell 图标缺少未读 badge 数字**：只有蓝点，无数量提示

## 已通过 ✅

- 颜色全部走 token，未发现硬编码 `#xxx` 或 Tailwind `gray-*`
- 圆角统一 `rounded-[var(--radius-*)]`
- 主品牌色仅用于"升级到 Pro"CTA、当前选中态（"文件"高亮），符合"品牌色仅用于 CTA / 选中态"规则
