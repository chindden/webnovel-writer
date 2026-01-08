---
name: workflow-resume
purpose: 任务恢复时加载，指导中断恢复流程
---

<context>
此文件用于中断任务恢复。Claude 已知错误处理流程，这里只补充网文创作工作流特定的Step难度分级和恢复策略。
</context>

<instructions>

## Step 中断难度分级

| Step | 影响 | 难度 | 默认策略 |
|------|------|------|----------|
| Step 1 | 无副作用（仅读取） | ⭐ | 直接重新执行 |
| Step 2 | 半成品章节文件 | ⭐⭐ | **删除半成品**，从Step 1重新开始 |
| Step 3 | 部分实体未提取 | ⭐⭐ | 重新运行脚本（幂等） |
| Step 4 | state.json 部分更新 | ⭐⭐⭐ | 检测一致性，回滚或补全 |
| Step 5 | strand_tracker 未更新 | ⭐⭐ | 重新运行脚本 |
| Step 6 | 审查未完成 | ⭐⭐⭐⭐⭐ | 用户决定：重审（成本高）或跳过 |
| Step 7 | Git未提交 | ⭐⭐⭐⭐ | 检查暂存区，决定提交/回滚 |

## 恢复流程

### Phase 1: 检测中断状态

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_manager.py" detect
```

### Phase 2: 询问用户

**必须展示**:
- 任务命令和参数
- 中断时间和位置
- 已完成步骤
- 恢复选项和风险等级

### Phase 3: 执行恢复

**选项 A（推荐）**: 删除半成品重新开始
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_manager.py" cleanup --chapter {N}
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_manager.py" clear
/webnovel-write {N}
```

**选项 B**: 回滚到上一章
```bash
git reset --hard ch{N-1:04d}
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_manager.py" clear
```

## 为什么删除而不续写？

1. **质量保证**: 半成品可能包含未完成句子、逻辑断裂
2. **上下文丢失**: 新会话无法记住之前创作思路
3. **防幻觉**: 续写容易产生前后矛盾
4. **成本可控**: 重新生成 < 修复半成品 + 审查

## 特殊场景

| 场景 | 策略 |
|------|------|
| 超过24小时 | 推荐回滚（上下文完全丢失） |
| 超过1小时 | 推荐重新开始 |
| 多个半成品 | 删除所有，从稳定状态重新开始 |
| workflow_state.json不存在 | 启发式检测 state.json vs 文件 |

</instructions>

<examples>

<example>
<input>Step 2 中断（最常见）</input>
<output>
🔴 检测到中断任务：

任务：/webnovel-write 7
中断位置：Step 2 - 章节内容生成中

已完成：
  ✅ Step 1: 上下文加载

未完成：
  ⏸️ Step 2: 章节内容（已写1500字）
  ⏹️ Step 3-7: 未开始

恢复选项：
A) 删除半成品，从Step 1重新开始（推荐）⭐
B) 回滚到Ch6，放弃Ch7所有进度

请选择（A/B）：
</output>
</example>

<example>
<input>Step 6 中断（成本高）</input>
<output>
恢复选项：
A) 重新执行双章审查（成本：~$0.15）⚠️
   - 调用5个审查员
   - 生成审查报告

B) 跳过审查，继续下一章（推荐）
   - 不生成审查报告
   - 可后续用 /webnovel-review 补审

请选择（A/B）：
</output>
</example>

</examples>

<errors>
❌ 智能续写半成品 → ✅ 删除后重新生成
❌ 自动决定恢复策略 → ✅ 必须用户确认
❌ 跳过中断检测 → ✅ 先运行 workflow_manager.py detect
❌ 修复 state.json 不验证 → ✅ 逐字段检查一致性
</errors>
