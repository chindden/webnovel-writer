---
name: core-constraints
purpose: 每次章节写作前加载，确保三大定律执行
---

<context>
此文件用于章节创作时的核心约束检查。Claude 已知一般写作规范，这里只补充网文特定的防幻觉协议。
</context>

<instructions>

## 三大定律（低自由度 - 必须精确执行）

| 定律 | 规则 | 违规标记 |
|------|------|----------|
| **大纲即法律** | 严格执行大纲，不得擅自发挥 | `<deviation reason="..."/>` |
| **设定即物理** | 实力/招式/物品 ≤ state.json | 检查后方可使用 |
| **发明需申报** | 新实体必须 XML 标签标记 | 见下方格式 |

## XML 标签格式

```xml
<!-- 新实体（章节末尾） -->
<entity type="角色|地点|物品|势力|功法" name="名称" desc="描述" tier="核心|支线|装饰"/>
<skill name="技能名" level="等级" desc="描述" cooldown="冷却"/>
<foreshadow content="内容" tier="核心|支线|装饰" target="目标章节"/>
```

## 爽点密度要求

- 每章 ≥1 个爽点
- 每 5 章 ≥1 个大爽点
- 避免连续 3 章同类型

## Strand 平衡警告

| 情节线 | 警告条件 |
|--------|----------|
| Quest（主线） | 连续 5+ 章 |
| Fire（感情线） | >10 章未出现 |
| Constellation（世界观） | >15 章未出现 |

## 禁止事项

- `[待补充]`、`[TODO]`、`...（省略）...` → 必须完整写出
- 战斗后无善后描述（都市异能题材）

</instructions>

<examples>

<example>
<input>主角需要使用"天雷掌"击败敌人</input>
<output>
1. 检查 state.json → protagonist_state.skills 是否包含"天雷掌"
2. 若有：直接使用
3. 若无：先用 <skill name="天雷掌" .../> 声明获得途径
</output>
</example>

<example type="edge_case">
<input>剧情需要主角展示筑基期实力，但 state.json 显示练气期</input>
<output>
❌ 直接写筑基期战力 → 违反"设定即物理"
✅ 先安排突破场景，更新 state.json，再展示新实力
</output>
</example>

</examples>

<errors>
❌ 无 XML 标签引入新角色 → ✅ 使用 `<entity type="角色" .../>`
❌ 主角突然会新技能 → ✅ 先声明获得途径
❌ 忘记更新 state.json → ✅ Step 4 强制更新
</errors>
