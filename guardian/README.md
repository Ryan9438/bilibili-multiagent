# guardian · 放行门禁

「机器醒着 ≠ 人醒着」——看片消耗配额前先确认人真的在。三种模式（GUARDIAN_MODE）：

- `manual`：用户点菜单栏鲸鱼 🐋 显式放行（AwakeWindow.app，源码 AwakeWindow.swift，swiftc 编译）；窗口剩余时长决定 level（watch/comments/reply）
- `time_window`：按配置时段判断，非 macOS 等价可用
- `none`：Tier 0 只读模式不需要

- `awake_gate.py watch`：本趟第一件事，按返回 level 走，别自己估
- 窗口是**机器属性**，多号共用；提前开干 = 窗口就是授权
