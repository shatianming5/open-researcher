# VHS Tape: PaperFarm run 完整流程
# 用法: vhs docs/assets/demo-start.tape
# 需要: 一个已 init 的项目目录

Output docs/assets/demo-start.gif

Set Shell "zsh"
Set FontSize 14
Set Width 1200
Set Height 700
Set Theme "Tokyo Night"
Set Padding 20
Set Framerate 30

Type "# PaperFarm — 零配置自动研究流程"
Enter
Sleep 1s

Type "PaperFarm run --agent claude-code"
Sleep 500ms
Enter
Sleep 8s

# Scout 阶段运行中，等待分析完成
Sleep 5s

# 展示 Tab 切换
Type "2"
Sleep 2s
Type "3"
Sleep 2s
Type "5"
Sleep 2s
Type "1"
Sleep 3s

# 回到 Overview 观察实验进行
Sleep 10s

Type "q"
Sleep 1s
