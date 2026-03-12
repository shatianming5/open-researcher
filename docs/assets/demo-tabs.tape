# VHS Tape: TUI 仪表盘 Tab 切换展示
# 用法: vhs docs/assets/demo-tabs.tape
# 前提: 有一个正在运行实验的 PaperFarm 实例

Output docs/assets/demo-tabs.gif

Set Shell "zsh"
Set FontSize 14
Set Width 1200
Set Height 700
Set Theme "Tokyo Night"
Set Padding 20
Set Framerate 30

Type "PaperFarm run --agent claude-code"
Sleep 500ms
Enter
Sleep 5s

# Tab 1: Overview — 状态总览
Sleep 2s

# Tab 2: Ideas — 想法列表
Type "2"
Sleep 3s

# Tab 3: Charts — 指标趋势图
Type "3"
Sleep 3s

# Tab 4: Logs — 实时日志
Type "4"
Sleep 3s

# Tab 5: Docs — 文档查看器
Type "5"
Sleep 2s

# 切换到 ideas.md 查看动态生成的表格
Sleep 3s

# 回到 Overview
Type "1"
Sleep 2s

Type "q"
Sleep 1s
