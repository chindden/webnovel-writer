---
name: system-data-flow
purpose: 项目初始化和状态查询时加载，理解数据结构
version: "4.0"
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
    ├── state.json          # 权威状态（entities_v3 + alias_index + 进度/主角）
    ├── workflow_state.json # 工作流断点（用于 /webnovel-resume）
    ├── index.db            # SQLite 索引（章节/实体/别名/关系/伏笔，可重建）
    └── archive/            # 归档数据（不活跃角色/已回收伏笔）
```

## 脚本职责速查 (v4.0)

| 脚本 | 输入 | 输出 |
|------|------|------|
| `init_project.py` | 无 | 生成 `.webnovel/state.json` 等 |
| `extract_entities.py` | 章节文件 | 更新 `entities_v3`/`alias_index`/`plot_threads`/`structured_relationships` + 同步 `设定集/` |
| `update_state.py` | 参数 | 原子更新 `state.json` 字段（进度/主角） |
| `structured_index.py` | 章节 + state | 写入 `.webnovel/index.db`（只读派生，不回写 state） |
| `context_pack_builder.py` | 章节号 | 生成结构化上下文包 JSON |
| `status_reporter.py` | 无 | 生成健康报告/伏笔紧急度 |
| `archive_manager.py` | 无 | 归档不活跃数据 |

## 每章数据链（v4.0 顺序）

```
1. 写/保存章节 → 正文/...
2. extract_entities.py --chapter N --auto
   → 解析 XML 标签 → 更新 entities_v3/alias_index → 同步设定集
3. metadata-extractor 子代理 → 临时 JSON（标题/出场角色/字数）
4. structured_index.py --update-chapter N
   → 写入 index.db（只读派生，不回写 state.json）
5. update_state.py --progress N WORDS
   → 更新进度/主角状态
6. Git 备份（强制）
```

**关键约束（v4.0）**:
- 索引层（structured_index.py）不写回 state.json
- alias_index 为一对多格式（同一别名可映射多个实体）
- 只支持 XML 格式标签，不再支持方括号格式

## state.json 核心字段 (v4.0)

```json
{
  "entities_v3": {
    "角色": {"entity_id": {...}},
    "地点": {...},
    "物品": {...},
    "势力": {...},
    "招式": {...}
  },
  "alias_index": {
    "别名": [{"type": "角色", "id": "entity_id"}, ...]
  },
  "protagonist_state": {...},
  "progress": {"current_chapter": N, "total_words": W},
  "plot_threads": {"foreshadowing": [...]},
  "structured_relationships": [...]
}
```

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
<input>查询实体别名</input>
<output>
```bash
cat .webnovel/state.json | jq '.alias_index["林天"]'
# 输出: [{"type": "角色", "id": "lintian"}]
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
❌ 使用方括号标签 [NEW_ENTITY] → ✅ v4.0 只支持 XML 格式
❌ alias_index 期望单对象 → ✅ v4.0 改为数组格式
</errors>
