---
description: 快速查询设定集信息（角色/实力/势力/物品/伏笔）
argument-hint: [查询类型] [关键词]
allowed-tools: Read, Bash, Grep
---

# /webnovel-query

查询项目数据，优先使用索引而非全库扫描。

## 查询类型

| 类型 | 示例 | 数据源 |
|------|------|--------|
| `角色` | `/webnovel-query 角色 林天` | 设定集/角色/ |
| `实力` | `/webnovel-query 实力 主角` | state.json |
| `势力` | `/webnovel-query 势力 天剑宗` | 设定集/势力/ |
| `物品` | `/webnovel-query 物品 玄天剑` | 设定集/物品/ |
| `伏笔` | `/webnovel-query 伏笔 紧急` | state.json + 伏笔紧急度分析 |
| `金手指` | `/webnovel-query 金手指` | state.json |

## 参数

- `$1`: 查询类型
- `$2`: 关键词（可选）

## 参考 Skill

详细流程见 `info-query` Skill。
