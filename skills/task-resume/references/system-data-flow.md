---
name: system-data-flow
purpose: 项目初始化和状态查询时加载，理解数据结构
---

<context>
此文件用于项目数据结构参考。Claude 已知一般文件组织，这里只补充网文工作流特定的目录约定和脚本职责。
</context>

<instructions>

## 目录约定

```
项目根目录/
├── 正文/           # 章节文件（第0001章.md 或 第1卷/第001章-标题.md）
├── 大纲/           # 卷纲/章纲/场景纲
├── 设定集/         # 世界观/力量体系/角色卡/物品卡
└── .webnovel/
    ├── state.json          # 唯一权威状态（角色/伏笔/进度/主角状态）
    ├── workflow_state.json # 工作流断点（用于 /webnovel-resume）
    ├── index.db            # SQLite 索引（章节/角色/伏笔快速查询）
    └── archive/            # 归档数据（不活跃角色/已回收伏笔）
```

## 脚本职责速查

| 脚本 | 输入 | 输出 |
|------|------|------|
| `init_project.py` | 无 | 生成 `.webnovel/state.json` 等 |
| `extract_entities.py` | 章节文件 | 更新 `设定集/` + `state.json` |
| `update_state.py` | 参数 | 原子更新 `state.json` 字段 |
| `structured_index.py` | 章节 | 写入 `.webnovel/index.db` |
| `status_reporter.py` | 无 | 生成健康报告/伏笔紧急度 |
| `archive_manager.py` | 无 | 归档不活跃数据 |
| `context_pack_builder.py` | 章节号 | 生成滑动窗口上下文 |

## 每章数据链（推荐顺序）

1. 写/保存章节 → `正文/...`
2. `metadata-extractor` 抽取元数据
3. `structured_index.py --update-chapter` 更新索引
4. `extract_entities.py --chapter N --auto` 同步设定集
5. `update_state.py --progress N WORDS` 更新状态
6. `archive_manager.py --auto-check` 可选归档
7. Git 备份（强制）

## 伏笔字段规范

| 字段 | 规范值 | 兼容值（历史） |
|------|--------|---------------|
| status | `未回收` / `已回收` | 待回收/进行中/active/pending |

**推荐字段**: content, status, planted_chapter, target_chapter, tier

</instructions>

<examples>

<example>
<input>查询当前进度</input>
<output>
```bash
cat .webnovel/state.json | jq '.progress'
# 输出: { "current_chapter": 45, "total_words": 135000 }
```
</output>
</example>

<example>
<input>检查伏笔紧急度</input>
<output>
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/status_reporter.py" --focus urgency
```
</output>
</example>

</examples>

<errors>
❌ 伏笔状态写成"待回收" → ✅ 使用规范值"未回收"
❌ 手工更新忘记加 planted_chapter → ✅ 脚本已自动补全
❌ 归档路径混淆 → ✅ 固定为 `.webnovel/archive/*.json`
</errors>
