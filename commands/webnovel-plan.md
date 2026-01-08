---
description: 规划指定卷的详细大纲（章节级别），含爽点和节奏预规划
argument-hint: [卷号]
allowed-tools: Read, Write, Edit, Bash, Task
---

# /webnovel-plan

将总纲细化为指定卷的章节级大纲。

## 执行流程

1. **读取总纲和前卷大纲**
2. **规划章节**：每章含剧情目标、爽点类型、Strand 主导
3. **输出**：`大纲/第X卷/卷纲.md` + 各章纲要
4. **更新 state.json**：卷/章规划信息

## 参数

- `$1`: 卷号（如 `1`、`2`）

## 参考 Skill

详细流程见 `outline-planning` Skill。
