# TUI 设计对比分析：Toad vs PaperFarm

## 1. 架构复杂度

| 维度 | Toad | PaperFarm |
|---|---|---|
| **Widget 文件数** | **38 个**独立 widget 文件 | **1 个** widgets.py（所有 widget 挤在一起） |
| **Screen 文件数** | 9 个 screen + 6 个独立 TCSS | 1 个 app.py + 1 个 review.py |
| **TCSS 文件** | 每个 screen 有独立 TCSS（main.tcss, settings.tcss, store.tcss...） | **1 个** styles.css（195 行，全局共享） |
| **CSS 规则量** | main.tcss 单个文件就 300+ 条规则 | 全部加起来不到 70 条规则 |

## 2. 视觉设计精细度

| 维度 | Toad | PaperFarm |
|---|---|---|
| **边框风格** | `round`, `panel`, `tall`, `heavy`, `wide` — 不同组件用不同边框 | 只用 `tall`，全场一种边框 |
| **透明度/层次** | 大量用 `opacity: 90%`, `background: $primary 10%`, `text-opacity: 0.5` 做层次感 | 无透明度运用，只有实色背景 |
| **状态样式** | 每个组件都有 `:focus`, `:hover`, `.-success`, `.-error`, `.-loading`, `.-maximized` 等多状态 | 基本无交互状态变化 |
| **动画/过渡** | Throbber 动画、blinking cursor (`.-blink`)、sidebar 滑入滑出 (`offset-x`) | 无任何动画 |
| **响应式** | `HORIZONTAL_BREAKPOINTS`、`-narrow`/`-wide` 类、`column_width` reactive 适配 | 无响应式设计 |

## 3. 组件设计理念

### Toad 的做法（专业级）

- **Diff 视图** (`diff_view.py`) — 专门的代码 diff 渲染组件
- **Throbber** — 加载动画指示器
- **Flash** — 闪烁效果组件
- **FutureText / StrikeText** — 文字动态效果
- **Mandelbrot** — 启动画面装饰（分形图）
- **CondensedPath** — 智能路径压缩显示
- **Plan widget** — 带 grid 布局的计划展示
- **Sidebar** — 可折叠、带 DirectoryTree 的侧边栏
- 每个 ToolCall 有展开/折叠、成功/失败/进行中三种边框颜色

### 我们的做法（功能级）

- 所有 widget 用 `Static` + Rich markup 手动拼字符串
- 进度条是手动 `"█" * filled + "░" * empty`
- 图表靠 plotext（基础终端图表）
- 没有独立的 diff 视图、没有动画、没有侧边栏

## 4. CSS 对比示例

### Toad 的 TerminalTool（一个组件的样式）

```css
TerminalTool {
    border: panel $primary 50%;
    background: $primary 10%;
    border-title-style: bold;
    &.-success {
        border: panel $success-muted;
        background: $success 7%;
        opacity: 90%;
    }
    &.-error {
        border: panel $error-muted;
        background: $error 7%;
        opacity: 90%;
    }
}
```

### 我们的 ExperimentStatus（同类组件的样式）

```css
#exp-status {
    height: auto;
    min-height: 3;
    max-height: 8;
    border: tall $primary-background;
    background: $panel;
    padding: 0 1;
}
```

## 5. 核心差距总结

| 差距 | 影响 |
|---|---|
| **Widget 全部堆在 1 个文件** | 无法独立迭代和精细化每个组件 |
| **CSS 只有 195 行** | 视觉层次扁平，缺乏精细打磨 |
| **无透明度/渐变** | 界面看起来"硬"，没有层次感 |
| **无动画** | 界面感觉静态、缺乏生命感 |
| **无响应式** | 窄终端下体验差 |
| **无交互状态** | hover/focus 没有视觉反馈 |
| **手动拼字符串渲染** | 不如用 Textual 原生 widget 组合灵活 |

## 6. 改进路线建议

1. 把 widgets.py 拆成独立组件文件（每个 widget 一个文件 + 配套 TCSS）
2. 给每个组件加 `.-success`/`.-error`/`:focus` 状态样式
3. 用透明度（`background: $primary 10%`）做视觉层次
4. 加入 Throbber/加载动画
5. 加响应式断点适配（`HORIZONTAL_BREAKPOINTS`）
6. 用 Textual 原生 widget 替代手动 Rich markup 拼接
7. 为不同边框场景使用 `round`/`panel`/`tall` 等多种风格

## 7. 背景说明

- **Toad 作者**：Will McGugan — Textual 框架本身的作者，对框架能力的利用是专家级的
- **Toad 定位**：通用 AI 编码助手终端界面，消费级产品
- **PaperFarm 定位**：研究实验自动化监控面板，开发者工具

Toad 是 Textual 框架的专业级应用，38 个精细化组件 + 多状态样式 + 动画 + 响应式。我们的 TUI 是功能可用但视觉粗糙，所有 widget 挤在一个文件里，CSS 不到 200 行，没有动画、层次感和交互反馈。
