#!/usr/bin/env python3
"""
XML 标签提取与同步脚本 (v4.0)

功能：
1. 扫描指定章节正文，提取所有 XML 格式标签
2. 支持标签类型：
   - <entity>: 实体（角色/地点/物品/势力/招式）
   - <entity-alias>: 实体别名注册
   - <entity-update>: 实体属性更新（支持 set/unset/add/remove/inc）
   - <skill>: 金手指技能
   - <foreshadow>: 伏笔标签
   - <deviation>: 大纲偏离标记
   - <relationship>: 角色关系
3. 支持实体层级分类（核心/支线/装饰）
4. 同步到设定集对应文件
5. 更新 state.json（entities_v3 + alias_index 一对多）
6. 支持自动化模式和交互式模式

v4.0 变更：
- alias_index 改为一对多（同一别名可映射多个实体）
- 删除旧格式兼容代码
- 新增操作：<unset>/<add>/<remove>/<inc>
- 顶层字段白名单支持

使用方式：
  python extract_entities.py <章节文件> [--auto] [--dry-run]
  python extract_entities.py --project-root "path" --chapter 1 --auto
"""

import re
import json
import os
import shutil
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any

# ============================================================================
# 安全修复：导入安全工具函数（P0 CRITICAL）
# ============================================================================
from security_utils import sanitize_filename, create_secure_directory, atomic_write_json
from project_locator import resolve_project_root, resolve_state_file
from chapter_paths import find_chapter_file, extract_chapter_num_from_filename

# Windows 编码兼容性修复
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 实体类型与目标文件映射
ENTITY_TYPE_MAP = {
    "角色": "设定集/角色库/{category}/{name}.md",
    "地点": "设定集/世界观.md",
    "物品": "设定集/物品库/{name}.md",
    "势力": "设定集/世界观.md",
    "招式": "设定集/力量体系.md",
    "其他": "设定集/其他设定/{name}.md"
}

# 有效实体类型（v4.0 不再兼容旧别名）
VALID_ENTITY_TYPES = {"角色", "地点", "物品", "势力", "招式"}

# 顶层字段白名单（可通过 entity-update 直接修改）
TOP_LEVEL_FIELDS = {"tier", "desc", "canonical_name", "importance", "status", "parent"}


class AmbiguousAliasError(RuntimeError):
    """别名命中多个实体且无法消歧（必须改用 id 或补充 type）。"""


def normalize_entity_type(raw: Any) -> str:
    """验证实体类型（v4.0 不再支持别名转换）。"""
    t = str(raw or "").strip()
    if not t:
        return ""
    if t in VALID_ENTITY_TYPES:
        return t
    return ""  # 无效类型返回空

# 角色分类规则
ROLE_CATEGORY_MAP = {
    "主角": "主要角色",
    "配角": "次要角色",
    "反派": "反派角色",
    "路人": "次要角色"
}

# 实体层级权重（匹配伏笔三层级系统）
ENTITY_TIER_MAP = {
    "核心": {"weight": 3.0, "desc": "必须追踪，影响主线"},
    "core": {"weight": 3.0, "desc": "必须追踪，影响主线"},
    "支线": {"weight": 2.0, "desc": "应该追踪，丰富剧情"},
    "sub": {"weight": 2.0, "desc": "应该追踪，丰富剧情"},
    "装饰": {"weight": 1.0, "desc": "可选追踪，增加真实感"},
    "decor": {"weight": 1.0, "desc": "可选追踪，增加真实感"}
}

# ============================================================================
# 实体管理核心函数 (v3.0 新增)
# ============================================================================

def generate_entity_id(entity_type: str, name: str, existing_ids: set) -> str:
    """
    生成唯一实体 ID

    规则:
    1. 优先使用拼音（去空格、小写）
    2. 冲突时追加数字后缀
    3. 特殊前缀按类型

    Args:
        entity_type: 实体类型（角色/地点/物品/势力/招式）
        name: 实体名称
        existing_ids: 已存在的 ID 集合

    Returns:
        str: 唯一的实体 ID
    """
    # 类型前缀映射
    prefix_map = {
        "物品": "item_",
        "势力": "faction_",
        "招式": "skill_",
        "地点": "loc_"
        # 角色无前缀
    }

    # 尝试使用 pypinyin，如果不可用则用简单的 hash
    try:
        from pypinyin import lazy_pinyin
        pinyin = ''.join(lazy_pinyin(name))
        base_id = prefix_map.get(entity_type, '') + pinyin.lower()
    except ImportError:
        # pypinyin 不可用时，使用简化方案
        import hashlib
        hash_suffix = hashlib.md5(name.encode('utf-8')).hexdigest()[:8]
        base_id = prefix_map.get(entity_type, '') + hash_suffix

    # 清理非法字符
    base_id = re.sub(r'[^a-z0-9_]', '', base_id)

    # 处理冲突
    final_id = base_id
    counter = 1
    while final_id in existing_ids:
        final_id = f"{base_id}_{counter}"
        counter += 1

    return final_id


def resolve_entity_by_alias(alias: str, entity_type: Optional[str], state: dict) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
    """
    通过别名解析实体（v4.0 一对多版本）

    Args:
        alias: 别名或名称
        entity_type: 实体类型提示（可选，用于歧义消解）
        state: state.json 内容

    Returns:
        (entity_type, entity_id, entity_data) 或 (None, None, None)

    Raises:
        AmbiguousAliasError: 别名命中多个实体且无法消歧（必须改用 id 或补充 type）
        ValueError: alias_index 数据格式不符合 v4.0 规范
    """
    alias_index = state.get("alias_index", {})

    # alias_index 新格式: {"别名": [{"type": "角色", "id": "xxx"}, ...]}
    entries = alias_index.get(alias)
    if not entries:
        return (None, None, None)

    if not isinstance(entries, list):
        raise ValueError(
            f"alias_index 数据格式错误：期望 alias_index[{alias!r}] 为 list[{{type,id,...}}]，实际为 {type(entries).__name__}"
        )

    # 只有一个匹配 -> 直接返回
    if len(entries) == 1:
        ref = entries[0]
        et = ref.get("type", "")
        eid = ref.get("id", "")
        entities_v3 = state.get("entities_v3", {})
        entity_data = entities_v3.get(et, {}).get(eid)
        return (et, eid, entity_data) if entity_data else (None, None, None)

    # 多个匹配 -> 尝试用 type 消解
    if entity_type:
        matches = [e for e in entries if e.get("type") == entity_type]
        if len(matches) == 1:
            ref = matches[0]
            et = ref.get("type", "")
            eid = ref.get("id", "")
            entities_v3 = state.get("entities_v3", {})
            entity_data = entities_v3.get(et, {}).get(eid)
            return (et, eid, entity_data) if entity_data else (None, None, None)

    # 歧义无法消解：必须强制报错，避免写错实体
    raise AmbiguousAliasError(f"别名歧义: {alias!r} 命中 {len(entries)} 个实体，请改用 id 或补充 type 属性")


def ensure_entities_v3_structure(state: dict) -> dict:
    """
    确保 state.json 有 entities_v3 和 alias_index 结构

    entities_v3 格式:
    {
        "角色": {
            "lintian": {
                "id": "lintian",
                "canonical_name": "林天",
                "aliases": ["废物", "林天"],
                "tier": "核心",
                "current": {...},
                "history": [...],
                "created_chapter": 1
            }
        },
        "地点": {...},
        ...
    }

    alias_index 格式 (v4.0 一对多):
    {
        "废物": [{"type": "角色", "id": "lintian"}],
        "天云宗": [
            {"type": "地点", "id": "loc_tianyunzong"},
            {"type": "势力", "id": "faction_tianyunzong"}
        ],
        ...
    }
    """
    if "entities_v3" not in state:
        state["entities_v3"] = {
            "角色": {},
            "地点": {},
            "物品": {},
            "势力": {},
            "招式": {}
        }

    if "alias_index" not in state:
        state["alias_index"] = {}

    return state


_XML_ATTR_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(["\'])(.*?)\2', re.DOTALL)


def parse_xml_attributes(tag: str) -> Dict[str, str]:
    """从形如 `<tag a=\"1\" b='2'/>` 的片段中提取属性字典（不做 XML 语义校验）。"""
    attrs: Dict[str, str] = {}
    for m in _XML_ATTR_RE.finditer(tag):
        key = m.group(1).strip()
        value = m.group(3).strip()
        if not key:
            continue
        attrs[key] = value
    return attrs


def _line_number_from_index(text: str, index: int) -> int:
    return text[:index].count("\n") + 1


def extract_new_entities(file_path: str) -> List[Dict]:
    """
    从章节文件中提取所有实体标签（v4.0 仅支持 XML 格式）。

    支持 XML 形态：
      1) 自闭合：<entity type="角色" name="林天" desc="..." tier="核心" [id="lintian"] [任意属性...]/>
      2) 成对：
         <entity type="角色" id="lintian" name="林天" desc="..." tier="核心">
           <alias>废物</alias>
           <alias>林宗主</alias>
         </entity>

    Returns:
        List[Dict]: [{"type","name","desc","tier","id?","attrs","aliases","line","source_file"}, ...]
    """
    p = Path(file_path)
    text = p.read_text(encoding="utf-8")

    entities: List[Dict[str, Any]] = []

    # ============================================================
    # XML 成对格式: <entity ...> ... </entity>（用于内嵌 alias）
    # ============================================================
    block_pattern = re.compile(r"(?s)(<entity\b[^>]*>)(.*?)</entity>")
    for m in block_pattern.finditer(text):
        open_tag = m.group(1)
        body = m.group(2)
        attrs = parse_xml_attributes(open_tag)

        entity_type = str(attrs.get("type", "")).strip()
        entity_name = str(attrs.get("name", "")).strip()
        if not entity_type or not entity_name:
            continue

        # 验证 entity_type
        if entity_type not in VALID_ENTITY_TYPES:
            print(f"⚠️ 无效实体类型: {entity_type}（第{_line_number_from_index(text, m.start())}行），跳过")
            continue

        entity_desc = str(attrs.get("desc", "")).strip()
        entity_tier = str(attrs.get("tier", "支线")).strip() or "支线"
        if entity_tier.lower() not in ENTITY_TIER_MAP:
            entity_tier = "支线"

        entity_id = str(attrs.get("id", "")).strip() or None
        extra_attrs = {k: v for k, v in attrs.items() if k not in {"type", "id", "name", "desc", "tier"}}
        aliases = [a.strip() for a in re.findall(r"(?s)<alias>(.*?)</alias>", body) if str(a).strip()]

        entities.append(
            {
                "type": entity_type,
                "id": entity_id,
                "name": entity_name,
                "desc": entity_desc,
                "tier": entity_tier,
                "attrs": extra_attrs,
                "aliases": aliases,
                "line": _line_number_from_index(text, m.start()),
                "source_file": file_path,
            }
        )

    # ============================================================
    # XML 自闭合格式: <entity .../>
    # ============================================================
    self_closing_pattern = re.compile(r"<entity\b[^>]*?/\s*>")
    for m in self_closing_pattern.finditer(text):
        tag = m.group(0)
        attrs = parse_xml_attributes(tag)

        entity_type = str(attrs.get("type", "")).strip()
        entity_name = str(attrs.get("name", "")).strip()
        if not entity_type or not entity_name:
            continue

        # 验证 entity_type
        if entity_type not in VALID_ENTITY_TYPES:
            print(f"⚠️ 无效实体类型: {entity_type}（第{_line_number_from_index(text, m.start())}行），跳过")
            continue

        entity_desc = str(attrs.get("desc", "")).strip()
        entity_tier = str(attrs.get("tier", "支线")).strip() or "支线"
        if entity_tier.lower() not in ENTITY_TIER_MAP:
            entity_tier = "支线"

        entity_id = str(attrs.get("id", "")).strip() or None
        extra_attrs = {k: v for k, v in attrs.items() if k not in {"type", "id", "name", "desc", "tier"}}

        entities.append(
            {
                "type": entity_type,
                "id": entity_id,
                "name": entity_name,
                "desc": entity_desc,
                "tier": entity_tier,
                "attrs": extra_attrs,
                "aliases": [],
                "line": _line_number_from_index(text, m.start()),
                "source_file": file_path,
            }
        )

    return entities


def extract_entity_alias_ops(file_path: str) -> List[Dict[str, Any]]:
    """
    提取实体别名操作：
      <entity-alias id="lintian" alias="林宗主" context="成为宗主后"/>
      <entity-alias ref="林天" alias="不灭战神" context="晋升称号后"/>

    可选：type="角色|地点|物品|势力|招式" 用于 disambiguation。
    """
    p = Path(file_path)
    text = p.read_text(encoding="utf-8")

    results: List[Dict[str, Any]] = []
    pattern = re.compile(r"<entity[-_]alias\b[^>]*?/\s*>", re.IGNORECASE)
    for m in pattern.finditer(text):
        tag = m.group(0)
        attrs = parse_xml_attributes(tag)

        alias = str(attrs.get("alias", "")).strip()
        if not alias:
            continue

        results.append(
            {
                "id": str(attrs.get("id", "")).strip() or None,
                "ref": str(attrs.get("ref", "")).strip() or None,
                "type": str(attrs.get("type", "")).strip() or None,
                "alias": alias,
                "context": str(attrs.get("context", "")).strip(),
                "line": _line_number_from_index(text, m.start()),
                "source_file": file_path,
            }
        )

    return results


def extract_entity_update_ops(file_path: str) -> List[Dict[str, Any]]:
    """
    提取实体更新操作（v4.0 支持 set/unset/add/remove/inc）：
      <entity-update id="lintian">
        <set key="realm" value="筑基期一层" reason="突破"/>
        <unset key="bottleneck"/>
        <add key="titles" value="不灭战神"/>
        <remove key="allies" value="张三"/>
        <inc key="kill_count" delta="1"/>
      </entity-update>

      <entity-update ref="林宗主" type="角色">
        <set key="realm" value="金丹期"/>
      </entity-update>

    可选：type="角色|地点|物品|势力|招式" 用于 disambiguation。
    """
    p = Path(file_path)
    text = p.read_text(encoding="utf-8")

    results: List[Dict[str, Any]] = []

    block_pattern = re.compile(r"(?s)(<entity-update\b[^>]*>)(.*?)</entity-update>", re.IGNORECASE)
    for m in block_pattern.finditer(text):
        open_tag = m.group(1)
        body = m.group(2)
        attrs = parse_xml_attributes(open_tag)

        operations: List[Dict[str, Any]] = []

        # <set key="..." value="..." reason="..."/>
        for sm in re.finditer(r"<set\b[^>]*?/\s*>", body, re.IGNORECASE):
            set_attrs = parse_xml_attributes(sm.group(0))
            key = str(set_attrs.get("key", "")).strip()
            value = str(set_attrs.get("value", "")).strip()
            if not key:
                continue
            operations.append({
                "op": "set",
                "key": key,
                "value": value,
                "reason": str(set_attrs.get("reason", "")).strip()
            })

        # <unset key="..."/>
        for sm in re.finditer(r"<unset\b[^>]*?/\s*>", body, re.IGNORECASE):
            set_attrs = parse_xml_attributes(sm.group(0))
            key = str(set_attrs.get("key", "")).strip()
            if not key:
                continue
            operations.append({
                "op": "unset",
                "key": key,
                "reason": str(set_attrs.get("reason", "")).strip()
            })

        # <add key="..." value="..."/>
        for sm in re.finditer(r"<add\b[^>]*?/\s*>", body, re.IGNORECASE):
            set_attrs = parse_xml_attributes(sm.group(0))
            key = str(set_attrs.get("key", "")).strip()
            value = str(set_attrs.get("value", "")).strip()
            if not key or not value:
                continue
            operations.append({
                "op": "add",
                "key": key,
                "value": value,
                "reason": str(set_attrs.get("reason", "")).strip()
            })

        # <remove key="..." value="..."/>
        for sm in re.finditer(r"<remove\b[^>]*?/\s*>", body, re.IGNORECASE):
            set_attrs = parse_xml_attributes(sm.group(0))
            key = str(set_attrs.get("key", "")).strip()
            value = str(set_attrs.get("value", "")).strip()
            if not key or not value:
                continue
            operations.append({
                "op": "remove",
                "key": key,
                "value": value,
                "reason": str(set_attrs.get("reason", "")).strip()
            })

        # <inc key="..." delta="..."/>
        for sm in re.finditer(r"<inc\b[^>]*?/\s*>", body, re.IGNORECASE):
            set_attrs = parse_xml_attributes(sm.group(0))
            key = str(set_attrs.get("key", "")).strip()
            delta_str = str(set_attrs.get("delta", "1")).strip()
            if not key:
                continue
            try:
                delta = int(delta_str)
            except ValueError:
                delta = 1
            operations.append({
                "op": "inc",
                "key": key,
                "delta": delta,
                "reason": str(set_attrs.get("reason", "")).strip()
            })

        if not operations:
            continue

        results.append(
            {
                "id": str(attrs.get("id", "")).strip() or None,
                "ref": str(attrs.get("ref", "")).strip() or None,
                "type": str(attrs.get("type", "")).strip() or None,
                "operations": operations,
                "line": _line_number_from_index(text, m.start()),
                "source_file": file_path,
            }
        )

    return results


def extract_golden_finger_skills(file_path: str) -> List[Dict]:
    """
    从章节文件中提取金手指技能标签（v4.0 仅支持 XML 格式）

    XML 格式：
      <skill name="技能名" level="等级" desc="描述" cooldown="冷却时间"/>

      示例：
      <skill name="时间回溯" level="1" desc="回到10秒前的状态" cooldown="24小时"/>

    Returns:
        List[Dict]: [{"name": "吞噬", "level": "Lv1", "desc": "...", "cooldown": "10秒"}, ...]
    """
    skills = []

    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            xml_matches = re.findall(
                r'<skill\s+name=["\']([^"\']+)["\']\s+level=["\']([^"\']+)["\']\s+desc=["\']([^"\']+)["\']\s+cooldown=["\']([^"\']+)["\']\s*/?>',
                line
            )
            for match in xml_matches:
                skills.append({
                    "name": match[0].strip(),
                    "level": match[1].strip(),
                    "desc": match[2].strip(),
                    "cooldown": match[3].strip(),
                    "line": line_num,
                    "source_file": file_path
                })

    return skills


def extract_foreshadowing_json(file_path: str) -> List[Dict[str, Any]]:
    """
    从章节文件提取伏笔标签（v4.0 仅支持 XML 格式）

    XML 格式：
      <foreshadow content="伏笔内容" tier="层级" target="目标章节" location="地点" characters="角色1,角色2"/>

      示例：
      <foreshadow content="神秘老者留下的玉佩开始发光" tier="核心" target="50" location="废弃实验室" characters="陆辰"/>

    字段：
      - content (必填)
      - tier (可选: 核心/支线/装饰，默认 支线)
      - planted_chapter (可选: 默认由调用方补齐)
      - target_chapter / target (可选: 默认 planted_chapter + 100)
      - location (可选)
      - characters (可选: 逗号分隔字符串)
    """
    p = Path(file_path)
    text = p.read_text(encoding="utf-8")

    results: List[Dict[str, Any]] = []

    xml_pattern = re.compile(
        r'<foreshadow\s+'
        r'content=["\']([^"\']+)["\']\s+'
        r'tier=["\']([^"\']+)["\']'
        r'(?:\s+target=["\']([^"\']*)["\'])?'
        r'(?:\s+location=["\']([^"\']*)["\'])?'
        r'(?:\s+characters=["\']([^"\']*)["\'])?'
        r'\s*/?>',
        re.DOTALL
    )

    for m in xml_pattern.finditer(text):
        line_num = text[: m.start()].count("\n") + 1
        content = m.group(1).strip()
        if not content:
            continue

        tier = m.group(2).strip() or "支线"
        if tier.lower() not in ENTITY_TIER_MAP:
            tier = "支线"

        target_str = m.group(3)
        target_chapter = None
        if target_str:
            try:
                target_chapter = int(target_str.strip())
            except (TypeError, ValueError):
                pass

        location = (m.group(4) or "").strip()

        characters_str = m.group(5) or ""
        characters_list = [c.strip() for c in re.split(r"[,，]", characters_str) if c.strip()]

        results.append({
            "content": content,
            "tier": tier,
            "planted_chapter": None,
            "target_chapter": target_chapter,
            "location": location,
            "characters": characters_list,
            "line": line_num,
            "source_file": str(p),
        })

    return results


def extract_deviations(file_path: str) -> List[Dict[str, Any]]:
    """
    从章节文件提取大纲偏离标签（v4.0 仅支持 XML 格式）

    XML 格式：
      <deviation reason="偏离原因"/>

      示例：
      <deviation reason="临时灵感，增加李薇与陆辰的情感互动，为后续感情线铺垫"/>

    Returns:
        List[Dict]: [{"reason": "...", "line": 123}, ...]
    """
    p = Path(file_path)
    text = p.read_text(encoding="utf-8")

    results: List[Dict[str, Any]] = []

    xml_pattern = re.compile(
        r'<deviation\s+reason=["\']([^"\']+)["\']\s*/?>',
        re.DOTALL
    )

    for m in xml_pattern.finditer(text):
        line_num = text[: m.start()].count("\n") + 1
        reason = m.group(1).strip()
        if reason:
            results.append({
                "reason": reason,
                "line": line_num,
                "source_file": str(p),
            })

    return results


def extract_relationships(file_path: str) -> List[Dict[str, Any]]:
    """
    从章节文件提取角色关系标签

    XML 格式（推荐使用 entity_id，避免改名导致断链）：
      <relationship char1_id="lintian" char2_id="lixue" type="romance" intensity="60" desc="暧昧中，互有好感"/>
      <relationship char1="林天" char2="李雪" type="romance" intensity="60" desc="暧昧中，互有好感"/>

      示例：
      <relationship char1="林天" char2="李雪" type="romance" intensity="60" desc="暧昧中，互有好感"/>
      <relationship char1="林天" char2="王少" type="enemy" intensity="90" desc="杀父之仇"/>
      <relationship char1="林天" char2="云长老" type="mentor" intensity="80" desc="师徒关系，受其指点"/>

    关系类型 (type):
      - ally: 盟友
      - enemy: 敌人
      - romance: 恋人/暧昧
      - mentor: 师徒
      - debtor: 恩怨（欠人情/被欠）
      - family: 家族/血缘
      - rival: 竞争对手

    强度 (intensity): 0-100，越高关系越强烈

    Returns:
        List[Dict]: [{"char1","char2","char1_id?","char2_id?","type","intensity","desc",...}, ...]
    """
    p = Path(file_path)
    text = p.read_text(encoding="utf-8")

    results: List[Dict[str, Any]] = []

    valid_types = {"ally", "enemy", "romance", "mentor", "debtor", "family", "rival"}

    # XML 格式: <relationship .../>
    xml_pattern = re.compile(r"<relationship\b[^>]*?/\s*>", re.IGNORECASE)
    for m in xml_pattern.finditer(text):
        line_num = text[: m.start()].count("\n") + 1
        attrs = parse_xml_attributes(m.group(0))

        char1 = str(attrs.get("char1", "")).strip()
        char2 = str(attrs.get("char2", "")).strip()
        char1_id = str(attrs.get("char1_id", "")).strip() or None
        char2_id = str(attrs.get("char2_id", "")).strip() or None
        rel_type = str(attrs.get("type", "")).strip().lower() or "ally"
        intensity_str = str(attrs.get("intensity", "")).strip() or "50"
        desc = str(attrs.get("desc", "")).strip()

        if not ((char1_id or char1) and (char2_id or char2)):
            continue

        # 验证关系类型
        if rel_type not in valid_types:
            print(f"⚠️ 未知关系类型 '{rel_type}'（第{line_num}行），使用默认 'ally'")
            rel_type = "ally"

        # 解析强度
        try:
            intensity = int(intensity_str)
            intensity = max(0, min(100, intensity))  # 限制 0-100
        except ValueError:
            intensity = 50  # 默认中等强度

        results.append({
            "char1": char1,
            "char2": char2,
            "char1_id": char1_id,
            "char2_id": char2_id,
            "type": rel_type,
            "intensity": intensity,
            "desc": desc,
            "line": line_num,
            "source_file": str(p),
        })

    return results


def categorize_character(desc: str) -> str:
    """
    根据描述判断角色分类

    规则：
      - 包含"主角"/"林天" → 主要角色
      - 包含"反派"/"敌对"/"血煞门" → 反派角色
      - 其他 → 次要角色
    """
    if "主角" in desc or "重要" in desc:
        return "主要角色"
    elif "反派" in desc or "敌对" in desc or "血煞" in desc:
        return "反派角色"
    else:
        return "次要角色"

def generate_character_card(entity: Dict, category: str) -> str:
    """生成角色卡 Markdown 内容"""
    return f"""# {entity['name']}

> **首次登场**: {entity.get('source_file', '未知')}（第 {entity.get('line', '?')} 行）
> **创建时间**: {datetime.now().strftime('%Y-%m-%d')}

## 基本信息

- **姓名**: {entity['name']}
- **性别**: 待补充
- **年龄**: 待补充
- **身份**: {entity['desc']}
- **所属势力**: 待补充

## 实力设定

- **当前境界**: 待补充
- **擅长招式**: 待补充
- **特殊能力**: 待补充

## 性格特点

{entity['desc']}

## 外貌描述

待补充

## 人际关系

- **与主角**: 待补充

## 重要剧情

- 【第 X 章】{entity['desc']}

## 备注

自动提取自 `<entity/>` 标签，请补充完善。
"""

def update_world_view(entity: Dict, target_file: str, section: str):
    """更新世界观.md（追加地点/势力信息）"""
    if not os.path.exists(target_file):
        # 创建基础模板
        content = f"""# 世界观

## 地理

## 势力

## 历史背景

"""
        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(content)

    # 读取现有内容
    with open(target_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 追加到对应章节
    if section == "地理":
        entry = f"""
### {entity['name']}

{entity['desc']}

> 首次登场: {entity.get('source_file', '未知')}
"""
    elif section == "势力":
        entry = f"""
### {entity['name']}

{entity['desc']}

> 首次登场: {entity.get('source_file', '未知')}
"""

    # 在对应章节后追加
    pattern = f"## {section}"
    if pattern in content:
        content = content.replace(pattern, f"{pattern}\n{entry}")
    else:
        content += f"\n## {section}\n{entry}"

    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(content)

def update_power_system(entity: Dict, target_file: str):
    """更新力量体系.md（追加招式）"""
    if not os.path.exists(target_file):
        content = f"""# 力量体系

## 境界划分

## 修炼方法

## 招式库

"""
        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(content)

    with open(target_file, 'r', encoding='utf-8') as f:
        content = f.read()

    entry = f"""
### {entity['name']}

{entity['desc']}

> 首次登场: {entity.get('source_file', '未知')}
"""

    if "## 招式库" in content:
        content = content.replace("## 招式库", f"## 招式库\n{entry}")
    else:
        content += f"\n## 招式库\n{entry}"

    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(content)

def update_state_json(
    entities: List[Dict],
    state_file: str,
    golden_finger_skills: Optional[List[Dict]] = None,
    foreshadowing_items: Optional[List[Dict[str, Any]]] = None,
    relationship_items: Optional[List[Dict[str, Any]]] = None,
    entity_alias_ops: Optional[List[Dict[str, Any]]] = None,
    entity_update_ops: Optional[List[Dict[str, Any]]] = None,
    *,
    default_planted_chapter: Optional[int] = None,
):
    """更新 state.json（实体/别名/属性更新 + 金手指/伏笔/关系）。"""

    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    with open(state_file, 'r', encoding='utf-8') as f:
        state = json.load(f)

    first_seen_chapter = _to_int(default_planted_chapter, 0)
    project_root = Path(state_file).resolve().parent.parent

    # 确保存在金手指技能列表
    if 'protagonist_state' not in state:
        state['protagonist_state'] = {}
    golden_finger = state['protagonist_state'].get('golden_finger')
    if not isinstance(golden_finger, dict):
        golden_finger = {}
        state['protagonist_state']['golden_finger'] = golden_finger
    golden_finger.setdefault("name", "")
    golden_finger.setdefault("level", 1)
    golden_finger.setdefault("cooldown", 0)
    golden_finger.setdefault("skills", [])

    # --- 实体别名/更新系统（entities_v3 + alias_index）---
    state = ensure_entities_v3_structure(state)

    entity_alias_ops = entity_alias_ops or []
    entity_update_ops = entity_update_ops or []

    touched = set()

    def _normalize_entity_type(raw: Any) -> str:
        t = normalize_entity_type(raw)
        if not t or t not in state.get("entities_v3", {}):
            return ""
        return t

    def _normalize_first_appearance(source_file: Any) -> str:
        raw = str(source_file or "").strip()
        if not raw:
            return ""
        try:
            p = Path(raw)
            if not p.is_absolute():
                p = (Path.cwd() / p).resolve()
            if p == project_root or project_root in p.parents:
                return str(p.relative_to(project_root)).replace("\\", "/")
            return str(p).replace("\\", "/")
        except Exception:
            return raw.replace("\\", "/")

    def _resolve_by_id(entity_id: Any, entity_type: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[dict]]:
        eid = str(entity_id or "").strip()
        if not eid:
            return (None, None, None)

        if entity_type:
            et = _normalize_entity_type(entity_type)
            data = state.get("entities_v3", {}).get(et, {}).get(eid)
            return (et, eid, data) if isinstance(data, dict) else (None, None, None)

        hits: list[tuple[str, dict]] = []
        for et, bucket in (state.get("entities_v3") or {}).items():
            if isinstance(bucket, dict) and eid in bucket:
                data = bucket.get(eid)
                if isinstance(data, dict):
                    hits.append((et, data))
        if len(hits) == 1:
            return (hits[0][0], eid, hits[0][1])
        return (None, None, None)

    def _resolve_ref(ref: Any, entity_type: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[dict]]:
        """通过别名/名称解析实体（v4.0 使用一对多 alias_index）"""
        r = str(ref or "").strip()
        if not r:
            return (None, None, None)

        # 使用新版 resolve_entity_by_alias（支持一对多 + 歧义检测）
        et_hint = _normalize_entity_type(entity_type) if entity_type else None
        et, eid, data = resolve_entity_by_alias(r, et_hint, state)
        if et and eid and isinstance(data, dict):
            return (et, eid, data)

        return (None, None, None)

    def _register_alias(entity_type: str, entity_id: str, alias: Any, *, context: str = "", first_seen: int = 0) -> None:
        """注册别名到 alias_index（v4.0 一对多版本）"""
        a = str(alias or "").strip()
        if not a:
            return

        state.setdefault("alias_index", {})
        alias_index = state["alias_index"]

        # 新格式：alias_index[alias] = [{type, id, first_seen_chapter?, context?}, ...]
        entries = alias_index.get(a)
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise ValueError(
                f"alias_index 数据格式错误：期望 alias_index[{a!r}] 为 list[{{type,id,...}}]，实际为 {type(entries).__name__}"
            )

        # 检查是否已存在相同的 (type, id) 组合
        new_entry: Dict[str, Any] = {"type": entity_type, "id": entity_id}
        if first_seen:
            new_entry["first_seen_chapter"] = int(first_seen)
        if context:
            new_entry["context"] = context
        for existing in entries:
            if existing.get("type") == entity_type and existing.get("id") == entity_id:
                # 补齐首次出现/上下文（只填空缺）
                if first_seen and not existing.get("first_seen_chapter"):
                    existing["first_seen_chapter"] = int(first_seen)
                if context and not existing.get("context"):
                    existing["context"] = context
                return  # 已存在，无需重复注册

        # 添加新条目
        entries.append(new_entry)
        alias_index[a] = entries

        # 同时更新实体的 aliases 列表
        data = state.get("entities_v3", {}).get(entity_type, {}).get(entity_id)
        if not isinstance(data, dict):
            return
        data.setdefault("aliases", [])
        if a not in data["aliases"]:
            data["aliases"].append(a)

    def _ensure_v3_entity(entity_type: str, entity_id: str, canonical_name: str, *, tier: str, desc: str, first_appearance: str) -> dict:
        bucket = state.setdefault("entities_v3", {}).setdefault(entity_type, {})
        data = bucket.get(entity_id)
        if not isinstance(data, dict):
            data = {
                "id": entity_id,
                "canonical_name": canonical_name,
                "aliases": [],
                "tier": tier or "支线",
                "desc": desc or "",
                "current": {},
                "history": [],
                "created_chapter": first_seen_chapter or 1,
                "first_appearance": first_appearance or "",
            }
            bucket[entity_id] = data

        if canonical_name and not data.get("canonical_name"):
            data["canonical_name"] = canonical_name
        if tier and str(tier).lower() in ENTITY_TIER_MAP:
            data["tier"] = tier
        if desc:
            data["desc"] = desc
        if first_appearance and not data.get("first_appearance"):
            data["first_appearance"] = first_appearance

        data.setdefault("current", {})
        data.setdefault("history", [])
        data.setdefault("aliases", [])
        return data

    def _apply_operations(entity_type: str, entity_id: str, data: dict, operations: List[Dict[str, Any]]) -> None:
        """应用实体更新操作（v4.0 支持 set/unset/add/remove/inc + 顶层字段）"""
        if not operations:
            return

        current = data.setdefault("current", {})
        changes: Dict[str, Any] = {}
        reasons: Dict[str, str] = {}

        def _rename(new_name: str, reason: str = "") -> None:
            new_name = str(new_name or "").strip()
            if not new_name:
                return
            old_name = str(data.get("canonical_name", "")).strip()
            if old_name and old_name != new_name:
                _register_alias(entity_type, entity_id, old_name, first_seen=first_seen_chapter)
            data["canonical_name"] = new_name
            _register_alias(entity_type, entity_id, new_name, first_seen=first_seen_chapter)
            changes["canonical_name"] = new_name
            if reason:
                reasons["canonical_name"] = reason

        for op_item in operations:
            op = str(op_item.get("op", "set")).strip().lower()
            key = str(op_item.get("key", "")).strip()
            reason = str(op_item.get("reason", "")).strip()
            if not key:
                continue

            # 顶层字段处理
            if key in TOP_LEVEL_FIELDS:
                if op == "set":
                    value = str(op_item.get("value", "")).strip()
                    if key == "canonical_name":
                        _rename(value, reason)
                    elif key == "tier":
                        # 校验 tier 值
                        if value.lower() in ENTITY_TIER_MAP or value in {"核心", "支线", "装饰"}:
                            if data.get("tier") != value:
                                data["tier"] = value
                                changes["tier"] = value
                                if reason:
                                    reasons["tier"] = reason
                        else:
                            print(f"⚠️ 无效 tier 值: {value}，跳过")
                    else:
                        if data.get(key) != value:
                            data[key] = value
                            changes[key] = value
                            if reason:
                                reasons[key] = reason
                elif op == "unset":
                    if key in data:
                        del data[key]
                        changes[key] = None
                        if reason:
                            reasons[key] = reason
                continue

            # canonical_name 的特殊别名
            if key in {"name", "canonical_name"} and op == "set":
                value = str(op_item.get("value", "")).strip()
                _rename(value, reason)
                continue

            # current 字段操作
            if op == "set":
                value = str(op_item.get("value", "")).strip()
                prev = current.get(key)
                if prev != value:
                    current[key] = value
                    changes[key] = value
                    if reason:
                        reasons[key] = reason

            elif op == "unset":
                if key in current:
                    del current[key]
                    changes[key] = None
                    if reason:
                        reasons[key] = reason

            elif op == "add":
                value = str(op_item.get("value", "")).strip()
                if not value:
                    continue
                arr = current.get(key, [])
                if not isinstance(arr, list):
                    arr = [arr] if arr else []
                if value not in arr:
                    arr.append(value)
                    current[key] = arr
                    changes[key] = arr
                    if reason:
                        reasons[key] = reason

            elif op == "remove":
                value = str(op_item.get("value", "")).strip()
                if not value:
                    continue
                arr = current.get(key, [])
                if isinstance(arr, list) and value in arr:
                    arr.remove(value)
                    current[key] = arr
                    changes[key] = arr
                    if reason:
                        reasons[key] = reason

            elif op == "inc":
                delta = op_item.get("delta", 1)
                try:
                    delta = int(delta)
                except (TypeError, ValueError):
                    delta = 1
                prev = current.get(key, 0)
                try:
                    prev = int(prev)
                except (TypeError, ValueError):
                    prev = 0
                new_val = prev + delta
                current[key] = new_val
                changes[key] = new_val
                if reason:
                    reasons[key] = reason

        if first_seen_chapter:
            current["last_chapter"] = max(_to_int(current.get("last_chapter"), 0), first_seen_chapter)

        if changes:
            entry: Dict[str, Any] = {"chapter": first_seen_chapter or 0, "changes": changes}
            if reasons:
                entry["reasons"] = reasons
            entry["added_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data.setdefault("history", []).append(entry)

    # 1) 处理 <entity .../> / <entity>...</entity>
    for entity in entities or []:
        entity_type = _normalize_entity_type(entity.get("type", ""))
        name = str(entity.get("name", "")).strip()
        if not name:
            continue

        raw_id = entity.get("id")
        entity_id = (str(raw_id).strip() if raw_id is not None else "") or None
        data: Optional[dict] = None

        if entity_id:
            _, _, data = _resolve_by_id(entity_id, entity_type)
        else:
            _, rid, rdata = _resolve_ref(name, entity_type)
            if rid and isinstance(rdata, dict):
                entity_id = rid
                data = rdata

        if not entity_id:
            existing_ids = set((state.get("entities_v3") or {}).get(entity_type, {}).keys())
            entity_id = generate_entity_id(entity_type, name, existing_ids)

        first_appearance = _normalize_first_appearance(entity.get("source_file", ""))
        tier = str(entity.get("tier", "支线")).strip() or "支线"
        if tier.lower() not in ENTITY_TIER_MAP:
            tier = "支线"
        desc = str(entity.get("desc", "")).strip()

        data = _ensure_v3_entity(entity_type, entity_id, name, tier=tier, desc=desc, first_appearance=first_appearance)

        # canonical name & aliases
        _register_alias(entity_type, entity_id, str(data.get("canonical_name", "")).strip() or name, first_seen=first_seen_chapter)
        _register_alias(entity_type, entity_id, name, first_seen=first_seen_chapter)
        for alias in (entity.get("aliases") or []):
            _register_alias(entity_type, entity_id, alias, first_seen=first_seen_chapter)

        # attribute updates (auto mode)
        extra_attrs = entity.get("attrs") or {}
        if isinstance(extra_attrs, dict) and extra_attrs:
            ops = [{"op": "set", "key": k, "value": str(v), "reason": ""} for k, v in extra_attrs.items()]
            _apply_operations(entity_type, entity_id, data, ops)

        touched.add((entity_type, entity_id))

    # 2) 处理 <entity-alias .../>
    for op in entity_alias_ops:
        alias = str(op.get("alias", "")).strip()
        if not alias:
            continue

        hint = op.get("type")
        entity_type_hint = _normalize_entity_type(hint) if hint else None

        et: Optional[str] = None
        eid: Optional[str] = None
        data: Optional[dict] = None

        if op.get("id"):
            et, eid, data = _resolve_by_id(op.get("id"), entity_type_hint)
        elif op.get("ref"):
            et, eid, data = _resolve_ref(op.get("ref"), entity_type_hint)

        if not (et and eid and isinstance(data, dict)):
            print(f"??  entity-alias 无法解析引用: id={op.get('id')!r} ref={op.get('ref')!r}")
            continue

        _register_alias(et, eid, alias, context=str(op.get("context", "")).strip(), first_seen=first_seen_chapter)
        touched.add((et, eid))

    # 3) 处理 <entity-update>...</entity-update>
    for op in entity_update_ops:
        operations = op.get("operations") or []
        if not isinstance(operations, list) or not operations:
            continue

        hint = op.get("type")
        entity_type_hint = _normalize_entity_type(hint) if hint else None

        et: Optional[str] = None
        eid: Optional[str] = None
        data: Optional[dict] = None

        if op.get("id"):
            et, eid, data = _resolve_by_id(op.get("id"), entity_type_hint)
        elif op.get("ref"):
            et, eid, data = _resolve_ref(op.get("ref"), entity_type_hint)

        if not (et and eid and isinstance(data, dict)):
            print(f"⚠️ entity-update 无法解析引用: id={op.get('id')!r} ref={op.get('ref')!r}")
            continue

        _apply_operations(et, eid, data, operations)
        touched.add((et, eid))

    # 4) 更新金手指技能
    if golden_finger_skills:
        existing = state['protagonist_state']['golden_finger'].get('skills', [])
        if not isinstance(existing, list):
            existing = []
            state['protagonist_state']['golden_finger']['skills'] = existing

        existing_by_name = {s.get("name"): s for s in existing if isinstance(s, dict) and s.get("name")}
        for skill in golden_finger_skills:
            if not isinstance(skill, dict):
                continue

            name = str(skill.get("name", "")).strip()
            if not name:
                continue

            level = str(skill.get("level", "")).strip()
            desc = str(skill.get("desc", "")).strip()
            cooldown = str(skill.get("cooldown", "")).strip()
            source_file = str(skill.get("source_file", "")).strip()

            existing_skill = existing_by_name.get(name)
            if existing_skill is None:
                new_skill = {
                    "name": name,
                    "level": level,
                    "desc": desc,
                    "cooldown": cooldown,
                    "unlocked_at": source_file,
                    "added_at": datetime.now().strftime('%Y-%m-%d')
                }
                existing.append(new_skill)
                existing_by_name[name] = new_skill
                print(f"  ✨ 新增金手指技能: {name} ({level})")
                continue

            changed = False
            if level and existing_skill.get("level") != level:
                existing_skill["level"] = level
                changed = True
            if desc and existing_skill.get("desc") != desc:
                existing_skill["desc"] = desc
                changed = True
            if cooldown and existing_skill.get("cooldown") != cooldown:
                existing_skill["cooldown"] = cooldown
                changed = True
            if source_file and not existing_skill.get("unlocked_at"):
                existing_skill["unlocked_at"] = source_file
                changed = True

            if changed:
                existing_skill["updated_at"] = datetime.now().strftime('%Y-%m-%d')
                print(f"  🔁 更新金手指技能: {name} ({existing_skill.get('level', level)})")

    # 更新伏笔（结构化）
    if foreshadowing_items:
        state.setdefault("plot_threads", {"active_threads": [], "foreshadowing": []})
        state["plot_threads"].setdefault("foreshadowing", [])

        existing = state["plot_threads"]["foreshadowing"]

        for item in foreshadowing_items:
            content = str(item.get("content", "")).strip()
            if not content:
                continue

            planted = item.get("planted_chapter") or default_planted_chapter or 1
            try:
                planted = int(planted)
            except (TypeError, ValueError):
                planted = default_planted_chapter or 1

            target = item.get("target_chapter")
            if target is None:
                target = planted + 100
            try:
                target = int(target)
            except (TypeError, ValueError):
                target = planted + 100

            tier = str(item.get("tier", "支线")).strip() or "支线"
            if tier.lower() not in ENTITY_TIER_MAP:
                tier = "支线"

            location = str(item.get("location", "")).strip()
            characters = item.get("characters", [])
            if not isinstance(characters, list):
                characters = []

            found = None
            for old in existing:
                if old.get("content") == content:
                    found = old
                    break

            if found is None:
                existing.append({
                    "content": content,
                    "status": "未回收",
                    "tier": tier,
                    "planted_chapter": planted,
                    "target_chapter": target,
                    "location": location,
                    "characters": characters,
                    "added_at": datetime.now().strftime("%Y-%m-%d"),
                })
                print(f"  ?? 新增伏笔: {content[:30]}...")
            else:
                found["tier"] = tier
                found["planted_chapter"] = planted
                found["target_chapter"] = target
                if location:
                    found["location"] = location

                old_chars = found.get("characters", [])
                if not isinstance(old_chars, list):
                    old_chars = []
                merged = []
                seen = set()
                for n in [*old_chars, *characters]:
                    s = str(n).strip()
                    if not s or s in seen:
                        continue
                    merged.append(s)
                    seen.add(s)
                found["characters"] = merged

    # 更新关系（结构化，推荐使用 entity_id）
    if relationship_items:
        state.setdefault("structured_relationships", [])
        existing = state["structured_relationships"]

        for item in relationship_items:
            # 优先使用显式 entity_id；否则按别名解析（强制消歧）
            char1_id = str(item.get("char1_id", "") or "").strip()
            char2_id = str(item.get("char2_id", "") or "").strip()
            char1_ref = str(item.get("char1", "")).strip()
            char2_ref = str(item.get("char2", "")).strip()

            # relationship 只允许角色
            if char1_id:
                _, rid, rdata = _resolve_by_id(char1_id, "角色")
                if not rid or not isinstance(rdata, dict):
                    raise ValueError(f"relationship.char1_id 无法解析: {char1_id!r}")
                char1_id = rid
                char1_name = str(rdata.get("canonical_name", "")).strip() or char1_ref
            else:
                _, rid, rdata = _resolve_ref(char1_ref, "角色")
                if not rid or not isinstance(rdata, dict):
                    raise ValueError(f"relationship.char1 无法解析: {char1_ref!r}")
                char1_id = rid
                char1_name = str(rdata.get("canonical_name", "")).strip() or char1_ref

            if char2_id:
                _, rid, rdata = _resolve_by_id(char2_id, "角色")
                if not rid or not isinstance(rdata, dict):
                    raise ValueError(f"relationship.char2_id 无法解析: {char2_id!r}")
                char2_id = rid
                char2_name = str(rdata.get("canonical_name", "")).strip() or char2_ref
            else:
                _, rid, rdata = _resolve_ref(char2_ref, "角色")
                if not rid or not isinstance(rdata, dict):
                    raise ValueError(f"relationship.char2 无法解析: {char2_ref!r}")
                char2_id = rid
                char2_name = str(rdata.get("canonical_name", "")).strip() or char2_ref

            rel_type = str(item.get("type", "ally")).strip().lower() or "ally"
            intensity = item.get("intensity", 50)
            desc = str(item.get("desc", "")).strip()

            try:
                intensity = int(intensity)
                intensity = max(0, min(100, intensity))
            except (TypeError, ValueError):
                intensity = 50

            # 查找是否已存在相同关系
            found = None
            for old in existing:
                if (
                    old.get("char1_id") == char1_id
                    and old.get("char2_id") == char2_id
                    and old.get("type") == rel_type
                ):
                    found = old
                    break

            if found is None:
                existing.append({
                    "char1_id": char1_id,
                    "char2_id": char2_id,
                    "char1_name": char1_name,
                    "char2_name": char2_name,
                    "type": rel_type,
                    "intensity": intensity,
                    "description": desc,
                    "last_update_chapter": default_planted_chapter or 1,
                    "added_at": datetime.now().strftime("%Y-%m-%d"),
                })
                print(f"  💕 新增关系: {char1_name} ↔ {char2_name} ({rel_type}, 强度 {intensity})")
            else:
                # 更新强度和描述
                found["intensity"] = intensity
                found["description"] = desc
                found["last_update_chapter"] = default_planted_chapter or found.get("last_update_chapter", 1)
                found.setdefault("char1_name", char1_name)
                found.setdefault("char2_name", char2_name)
                print(f"  💕 更新关系: {char1_name} ↔ {char2_name} ({rel_type}, 强度 {intensity})")

    # 使用集中式原子写入（带 filelock + 自动备份）
    atomic_write_json(state_file, state, use_lock=True, backup=True)
    print(f"✅ state.json 已原子化更新（带备份）")

def sync_entity_to_settings(entity: Dict, project_root: str, auto_mode: bool = False) -> bool:
    """
    将实体同步到设定集

    Returns:
        bool: 是否成功同步
    """
    entity_type = normalize_entity_type(entity.get('type'))
    entity_name = entity['name']

    if entity_type == "角色":
        category = categorize_character(entity['desc'])
        category_dir = ROLE_CATEGORY_MAP.get(category.split('/')[0], "次要角色")

        target_dir = Path(project_root) / f"设定集/角色库/{category_dir}"
        # ============================================================================
        # 安全修复：使用安全目录创建函数（文件权限修复）
        # ============================================================================
        create_secure_directory(str(target_dir))

        # ============================================================================
        # 安全修复：清理文件名，防止路径遍历 (CWE-22) - P0 CRITICAL
        # 原代码: target_file = target_dir / f"{entity_name}.md"
        # 漏洞: entity_name可能包含 "../" 导致目录遍历攻击
        # ============================================================================
        safe_entity_name = sanitize_filename(entity_name)
        target_file = target_dir / f"{safe_entity_name}.md"

        if target_file.exists():
            print(f"⚠️  角色卡已存在: {target_file}")
            if not auto_mode:
                choice = input("是否覆盖？(y/n): ")
                if choice.lower() != 'y':
                    return False

        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(generate_character_card(entity, category))

        print(f"✅ 已创建角色卡: {target_file}")
        return True

    elif entity_type == "地点":
        target_file = Path(project_root) / "设定集/世界观.md"
        update_world_view(entity, str(target_file), "地理")
        print(f"✅ 已更新世界观（地理）: {entity_name}")
        return True

    elif entity_type == "势力":
        target_file = Path(project_root) / "设定集/世界观.md"
        update_world_view(entity, str(target_file), "势力")
        print(f"✅ 已更新世界观（势力）: {entity_name}")
        return True

    elif entity_type == "招式":
        target_file = Path(project_root) / "设定集/力量体系.md"
        update_power_system(entity, str(target_file))
        print(f"✅ 已更新力量体系（招式）: {entity_name}")
        return True

    elif entity_type == "物品":
        target_dir = Path(project_root) / "设定集/物品库"
        # ============================================================================
        # 安全修复：使用安全目录创建函数（文件权限修复）
        # ============================================================================
        create_secure_directory(str(target_dir))

        # ============================================================================
        # 安全修复：清理文件名，防止路径遍历 (CWE-22) - P0 CRITICAL
        # 原代码: target_file = target_dir / f"{entity_name}.md"
        # 漏洞: entity_name可能包含 "../" 导致目录遍历攻击
        # ============================================================================
        safe_entity_name = sanitize_filename(entity_name)
        target_file = target_dir / f"{safe_entity_name}.md"

        if target_file.exists():
            print(f"⚠️  物品卡已存在: {target_file}")
            if not auto_mode:
                choice = input("是否覆盖？(y/n): ")
                if choice.lower() != 'y':
                    return False

        content = f"""# {entity_name}

> **首次登场**: {entity.get('source_file', '未知')}
> **创建时间**: {datetime.now().strftime('%Y-%m-%d')}

## 基本信息

{entity['desc']}

## 详细设定

待补充

## 相关剧情

- 【第 X 章】首次出现

## 备注

自动提取自 `<entity/>` 标签，请补充完善。
"""

        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"✅ 已创建物品卡: {target_file}")
        return True

    else:
        print(f"⚠️  未知实体类型: {entity_type}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="XML 标签提取与同步 (<entity/>, <entity-alias/>, <entity-update>, <skill/>, <foreshadow/>, <deviation/>, <relationship/>)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 指定文件（兼容卷目录）
  python extract_entities.py "webnovel-project/正文/第1卷/第001章-死亡降临.md" --auto

  # 指定章节号（推荐）
  python extract_entities.py --project-root "webnovel-project" --chapter 1 --auto
""".strip(),
    )

    parser.add_argument("chapter_file", nargs="?", help="章节文件路径（或使用 --chapter）")
    parser.add_argument("--chapter", type=int, help="章节号（与 --project-root 配合，自动定位章节文件）")
    parser.add_argument("--project-root", default=None, help="项目根目录（包含 .webnovel/state.json）")
    parser.add_argument("--auto", action="store_true", help="自动模式（非交互）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入文件/状态")

    args = parser.parse_args()

    auto_mode = args.auto
    dry_run = args.dry_run

    project_root: Optional[Path] = None
    if args.project_root:
        project_root = resolve_project_root(args.project_root)
    else:
        try:
            project_root = resolve_project_root()
        except FileNotFoundError:
            project_root = None

    chapter_file: Optional[str] = None
    chapter_num: Optional[int] = None

    if args.chapter is not None:
        if not project_root:
            print("❌ 未提供有效的 --project-root，无法用 --chapter 定位章节文件")
            sys.exit(1)

        chapter_num = int(args.chapter)
        chapter_path = find_chapter_file(project_root, chapter_num)
        if not chapter_path:
            print(f"❌ 未找到第{chapter_num}章文件（请先生成/保存章节）")
            sys.exit(1)
        chapter_file = str(chapter_path)
    else:
        if not args.chapter_file:
            parser.error("必须提供 chapter_file 或 --chapter")
        chapter_file = args.chapter_file
        if not os.path.exists(chapter_file):
            print(f"❌ 文件不存在: {chapter_file}")
            sys.exit(1)

        chapter_num = extract_chapter_num_from_filename(Path(chapter_file).name)

    print(f"📖 正在扫描: {chapter_file}")
    entities = extract_new_entities(chapter_file)
    entity_alias_ops = extract_entity_alias_ops(chapter_file)
    entity_update_ops = extract_entity_update_ops(chapter_file)
    golden_finger_skills = extract_golden_finger_skills(chapter_file)
    foreshadowing_items = extract_foreshadowing_json(chapter_file)
    deviations = extract_deviations(chapter_file)
    relationship_items = extract_relationships(chapter_file)

    if not entities and not entity_alias_ops and not entity_update_ops and not golden_finger_skills and not foreshadowing_items and not deviations and not relationship_items:
        print("✅ 未发现任何 XML 标签（<entity>/<entity-alias>/<entity-update>/<skill>/<foreshadow>/<deviation>/<relationship>）")
        return

    if entities:
        print(f"\n🔍 发现 {len(entities)} 个新实体：")
        for i, entity in enumerate(entities, 1):
            tier_emoji = {"核心": "🔴", "支线": "🟡", "装饰": "🟢"}.get(entity.get("tier", "支线"), "⚪")
            print(
                f"  {i}. [{entity['type']}] {entity['name']} {tier_emoji}{entity.get('tier', '支线')} - {entity['desc'][:25]}..."
            )

    if golden_finger_skills:
        print(f"\n✨ 发现 {len(golden_finger_skills)} 个金手指技能：")
        for i, skill in enumerate(golden_finger_skills, 1):
            print(f"  {i}. {skill['name']} ({skill['level']}) - {skill['desc'][:25]}...")

    if entity_alias_ops:
        print(f"\n🏷️ 发现 {len(entity_alias_ops)} 条实体别名：")
        for i, op in enumerate(entity_alias_ops, 1):
            ref = op.get("id") or op.get("ref") or "?"
            print(f"  {i}. {ref} -> {op.get('alias', '')}")

    if entity_update_ops:
        print(f"\n🛠️ 发现 {len(entity_update_ops)} 条实体更新：")
        for i, op in enumerate(entity_update_ops, 1):
            ref = op.get("id") or op.get("ref") or "?"
            operations = op.get("operations") or []
            ops_preview = []
            for o in operations[:6]:
                if isinstance(o, dict):
                    op_type = o.get("op", "set")
                    key = o.get("key", "")
                    ops_preview.append(f"{op_type}:{key}")
            preview = ", ".join(ops_preview) + ("..." if len(operations) > 6 else "")
            print(f"  {i}. {ref}: {preview}")

    if foreshadowing_items:
        print(f"\n🧩 发现 {len(foreshadowing_items)} 条伏笔：")
        for i, item in enumerate(foreshadowing_items, 1):
            tier = item.get("tier", "支线")
            target = item.get("target_chapter", "未设定")
            print(f"  {i}. {tier} → 目标Ch{target}: {str(item.get('content', ''))[:40]}...")

    if deviations:
        print(f"\n⚡ 发现 {len(deviations)} 条大纲偏离：")
        for i, dev in enumerate(deviations, 1):
            print(f"  {i}. {dev.get('reason', '')[:50]}...")

    if relationship_items:
        print(f"\n💕 发现 {len(relationship_items)} 条关系：")
        for i, rel in enumerate(relationship_items, 1):
            char1 = str(rel.get("char1") or rel.get("char1_id") or "").strip() or "?"
            char2 = str(rel.get("char2") or rel.get("char2_id") or "").strip() or "?"
            print(f"  {i}. {char1} ↔ {char2} ({rel['type']}, 强度 {rel['intensity']})")

    if dry_run:
        print("\n⚠️  Dry-run 模式，不执行实际写入")
        return

    if not project_root:
        chapter_path = Path(chapter_file).resolve()
        for parent in [chapter_path.parent] + list(chapter_path.parents):
            if (parent / ".webnovel" / "state.json").exists():
                project_root = parent
                break

    if not project_root:
        print("❌ 找不到项目根目录（缺少 .webnovel/state.json）")
        print("请先运行 /webnovel-init 初始化项目，或使用 --project-root 指定路径")
        sys.exit(1)

    state_file = resolve_state_file(explicit_project_root=str(project_root))

    print("\n📝 开始同步到设定集...")
    success_count = 0
    for entity in entities:
        if sync_entity_to_settings(entity, str(project_root), auto_mode):
            success_count += 1

    print("\n💾 更新 state.json...")
    try:
        update_state_json(
            entities=entities,
            state_file=str(state_file),
            golden_finger_skills=golden_finger_skills,
            foreshadowing_items=foreshadowing_items,
            relationship_items=relationship_items,
            entity_alias_ops=entity_alias_ops,
            entity_update_ops=entity_update_ops,
            default_planted_chapter=chapter_num,
        )
    except (AmbiguousAliasError, ValueError) as e:
        print(f"❌ {e}")
        sys.exit(2)

    print("\n✅ 完成！")
    print(f"  - 实体同步: {success_count}/{len(entities)} 个")
    if golden_finger_skills:
        print(f"  - 金手指技能: {len(golden_finger_skills)} 个")
    if foreshadowing_items:
        print(f"  - 伏笔同步: {len(foreshadowing_items)} 条")
    if relationship_items:
        print(f"  - 关系同步: {len(relationship_items)} 条")
    if deviations:
        print(f"  - 大纲偏离: {len(deviations)} 条（仅记录，不同步到 state.json）")

    if not auto_mode:
        print("\n💡 建议:")
        print("  1. 检查生成的角色卡/物品卡，补充详细设定")
        print("  2. 查看 世界观.md 和 力量体系.md 的更新")
        print("  3. 确认 .webnovel/state.json 中的实体记录")
        if golden_finger_skills:
            print("  4. 检查金手指技能是否正确记录在 protagonist_state.golden_finger.skills")
        if foreshadowing_items:
            print("  5. 检查 plot_threads.foreshadowing 的 planted/target/tier/location/characters 是否合理")
        if relationship_items:
            print("  6. 检查 structured_relationships 关系记录是否合理")
        if deviations:
            print("  7. 大纲偏离已记录，请在 plan.md 或大纲中同步调整")

if __name__ == "__main__":
    main()
