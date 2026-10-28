---
tags: [skill-creator]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

我用 Phaser 3 做了一个横版跑酷，打算发到 B站 Toy。现在在B站App里打开是竖屏的，要玩家自己横过来很难受；我想进游戏时自动切横屏全屏。另外有人反馈：全屏后左上角的暂停按钮被顶部那个胶囊按钮挡住了，还有时候横屏后整个画面缩成很小一块，要过一会儿才正常。帮我写一个 src/toy-container.ts 模块解决这些问题，并告诉我在 Phaser 的 main.ts 里怎么接入。
