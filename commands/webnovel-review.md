---
description: 对指定范围章节进行质量审查（爽点/设定/节奏/OOC/连续性）
argument-hint: [章节范围，如 1-10 或 5]
allowed-tools: Read, Write, Bash, Task
---

# /webnovel-review

对章节进行全面质量审查。

## 执行流程

1. **解析范围**：单章（`5`）或范围（`1-10`）
2. **并行调用 5 个检查员**：
   - `high-point-checker` - 爽点密度和质量
   - `consistency-checker` - 设定一致性
   - `pacing-checker` - Strand Weave 节奏
   - `ooc-checker` - 角色行为一致性
   - `continuity-checker` - 伏笔和剧情连续性
3. **生成报告**：`审查报告/review_ch{N}-{M}.md`
4. **更新 state**：`review_checkpoints` 追加记录

## 参数

- `$1`: 章节范围（如 `5` 或 `1-10`）

## 参考 Skill

详细流程见 `quality-review` Skill。
