---
description: 恢复中断的网文创作任务，基于 workflow_state.json 精确恢复
allowed-tools: Read, Write, Edit, Bash, AskUserQuestion, Task
---

# /webnovel-resume

检测并恢复中断的创作任务。

## 执行流程

1. **检测中断状态**：
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_manager.py" detect
   ```

2. **展示中断信息**：
   - 任务命令和参数
   - 中断时间和位置
   - 已完成/未完成步骤

3. **询问恢复策略**：
   - A) 删除半成品，重新开始（推荐）
   - B) 回滚到上一章
   - C) 跳过当前步骤继续

4. **执行恢复**

## 恢复原则

- **不续写半成品**：质量无法保证
- **必须用户确认**：不自动决定策略
- **原子性恢复**：恢复到一致状态

## 参考 Skill

详细流程见 `task-resume` Skill。
