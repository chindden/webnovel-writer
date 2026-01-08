#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
State Manager - 状态管理模块

管理 state.json 的读写操作：
- 实体状态管理
- 进度追踪
- 关系记录
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
import filelock

from .config import get_config


@dataclass
class EntityState:
    """实体状态"""
    id: str
    name: str
    type: str  # 角色/地点/物品/势力
    tier: str = "装饰"  # 核心/支线/装饰
    aliases: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    first_appearance: int = 0
    last_appearance: int = 0


@dataclass
class Relationship:
    """实体关系"""
    from_entity: str
    to_entity: str
    type: str
    description: str
    chapter: int


@dataclass
class StateChange:
    """状态变化记录"""
    entity_id: str
    field: str
    old_value: Any
    new_value: Any
    reason: str
    chapter: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class StateManager:
    """状态管理器"""

    def __init__(self, config=None):
        self.config = config or get_config()
        self._state: Dict[str, Any] = {}
        self._lock_path = self.config.state_file.with_suffix(".lock")
        self._load_state()

    def _load_state(self):
        """加载状态文件"""
        if self.config.state_file.exists():
            with open(self.config.state_file, "r", encoding="utf-8") as f:
                self._state = json.load(f)
        else:
            self._state = {
                "meta": {
                    "novel_name": "",
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                },
                "progress": {
                    "current_chapter": 0,
                    "total_words": 0
                },
                "entities": {},
                "relationships": [],
                "state_changes": []
            }

    def save_state(self):
        """保存状态文件（带文件锁）"""
        self.config.ensure_dirs()

        # 更新时间戳
        self._state["meta"]["updated_at"] = datetime.now().isoformat()

        lock = filelock.FileLock(str(self._lock_path), timeout=10)
        try:
            with lock:
                with open(self.config.state_file, "w", encoding="utf-8") as f:
                    json.dump(self._state, f, ensure_ascii=False, indent=2)
        except filelock.Timeout:
            raise RuntimeError("无法获取 state.json 文件锁，请稍后重试")

    # ==================== 进度管理 ====================

    def get_current_chapter(self) -> int:
        """获取当前章节号"""
        return self._state.get("progress", {}).get("current_chapter", 0)

    def update_progress(self, chapter: int, words: int = 0):
        """更新进度"""
        if "progress" not in self._state:
            self._state["progress"] = {}
        self._state["progress"]["current_chapter"] = chapter
        if words > 0:
            total = self._state["progress"].get("total_words", 0)
            self._state["progress"]["total_words"] = total + words

    # ==================== 实体管理 ====================

    def get_entity(self, entity_id: str) -> Optional[Dict]:
        """获取实体"""
        return self._state.get("entities", {}).get(entity_id)

    def get_all_entities(self) -> Dict[str, Dict]:
        """获取所有实体"""
        return self._state.get("entities", {})

    def get_entities_by_type(self, entity_type: str) -> Dict[str, Dict]:
        """按类型获取实体"""
        return {
            eid: e for eid, e in self._state.get("entities", {}).items()
            if e.get("type") == entity_type
        }

    def get_entities_by_tier(self, tier: str) -> Dict[str, Dict]:
        """按层级获取实体"""
        return {
            eid: e for eid, e in self._state.get("entities", {}).items()
            if e.get("tier") == tier
        }

    def add_entity(self, entity: EntityState) -> bool:
        """添加新实体"""
        if "entities" not in self._state:
            self._state["entities"] = {}

        if entity.id in self._state["entities"]:
            return False  # 已存在

        self._state["entities"][entity.id] = asdict(entity)
        return True

    def update_entity(self, entity_id: str, updates: Dict[str, Any]) -> bool:
        """更新实体属性"""
        if entity_id not in self._state.get("entities", {}):
            return False

        entity = self._state["entities"][entity_id]
        for key, value in updates.items():
            if key == "attributes" and isinstance(value, dict):
                if "attributes" not in entity:
                    entity["attributes"] = {}
                entity["attributes"].update(value)
            else:
                entity[key] = value

        return True

    def update_entity_appearance(self, entity_id: str, chapter: int):
        """更新实体出场章节"""
        entity = self.get_entity(entity_id)
        if entity:
            if entity.get("first_appearance", 0) == 0:
                entity["first_appearance"] = chapter
            entity["last_appearance"] = chapter

    # ==================== 状态变化记录 ====================

    def record_state_change(
        self,
        entity_id: str,
        field: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        chapter: int
    ):
        """记录状态变化"""
        if "state_changes" not in self._state:
            self._state["state_changes"] = []

        change = StateChange(
            entity_id=entity_id,
            field=field,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            chapter=chapter
        )
        self._state["state_changes"].append(asdict(change))

        # 同时更新实体属性
        self.update_entity(entity_id, {"attributes": {field: new_value}})

    def get_state_changes(self, entity_id: Optional[str] = None) -> List[Dict]:
        """获取状态变化历史"""
        changes = self._state.get("state_changes", [])
        if entity_id:
            changes = [c for c in changes if c.get("entity_id") == entity_id]
        return changes

    # ==================== 关系管理 ====================

    def add_relationship(
        self,
        from_entity: str,
        to_entity: str,
        rel_type: str,
        description: str,
        chapter: int
    ):
        """添加关系"""
        if "relationships" not in self._state:
            self._state["relationships"] = []

        rel = Relationship(
            from_entity=from_entity,
            to_entity=to_entity,
            type=rel_type,
            description=description,
            chapter=chapter
        )
        self._state["relationships"].append(asdict(rel))

    def get_relationships(self, entity_id: Optional[str] = None) -> List[Dict]:
        """获取关系列表"""
        rels = self._state.get("relationships", [])
        if entity_id:
            rels = [
                r for r in rels
                if r.get("from_entity") == entity_id or r.get("to_entity") == entity_id
            ]
        return rels

    # ==================== 批量操作 ====================

    def process_chapter_result(self, chapter: int, result: Dict) -> List[str]:
        """
        处理 Data Agent 的章节处理结果

        result 格式:
        {
            "entities_appeared": [...],
            "entities_new": [...],
            "state_changes": [...],
            "relationships": [...]
        }

        返回警告列表
        """
        warnings = []

        # 处理出场实体
        for entity in result.get("entities_appeared", []):
            entity_id = entity.get("id")
            if entity_id and entity_id != "NEW":
                self.update_entity_appearance(entity_id, chapter)

        # 处理新实体
        for entity in result.get("entities_new", []):
            entity_id = entity.get("suggested_id") or entity.get("id")
            if entity_id and entity_id != "NEW":
                new_entity = EntityState(
                    id=entity_id,
                    name=entity.get("name", ""),
                    type=entity.get("type", "角色"),
                    tier=entity.get("tier", "装饰"),
                    aliases=entity.get("mentions", []),
                    first_appearance=chapter,
                    last_appearance=chapter
                )
                if not self.add_entity(new_entity):
                    warnings.append(f"实体已存在: {entity_id}")

        # 处理状态变化
        for change in result.get("state_changes", []):
            self.record_state_change(
                entity_id=change.get("entity_id", ""),
                field=change.get("field", ""),
                old_value=change.get("old"),
                new_value=change.get("new"),
                reason=change.get("reason", ""),
                chapter=chapter
            )

        # 处理关系
        for rel in result.get("relationships", []):
            self.add_relationship(
                from_entity=rel.get("from", ""),
                to_entity=rel.get("to", ""),
                rel_type=rel.get("type", ""),
                description=rel.get("description", ""),
                chapter=chapter
            )

        # 更新进度
        self.update_progress(chapter)

        return warnings

    # ==================== 导出 ====================

    def export_for_context(self) -> Dict:
        """导出用于上下文的精简版状态"""
        return {
            "progress": self._state.get("progress", {}),
            "entities": {
                eid: {
                    "name": e.get("name"),
                    "type": e.get("type"),
                    "tier": e.get("tier"),
                    "aliases": e.get("aliases", [])
                }
                for eid, e in self._state.get("entities", {}).items()
            },
            "recent_changes": self._state.get("state_changes", [])[-20:]
        }


# ==================== CLI 接口 ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="State Manager CLI")
    parser.add_argument("--project-root", type=str, help="项目根目录")

    subparsers = parser.add_subparsers(dest="command")

    # 获取进度
    subparsers.add_parser("get-progress")

    # 获取实体
    get_entity_parser = subparsers.add_parser("get-entity")
    get_entity_parser.add_argument("--id", required=True, help="实体ID")

    # 列出实体
    list_parser = subparsers.add_parser("list-entities")
    list_parser.add_argument("--type", help="按类型过滤")
    list_parser.add_argument("--tier", help="按层级过滤")

    # 处理章节结果
    process_parser = subparsers.add_parser("process-chapter")
    process_parser.add_argument("--chapter", type=int, required=True, help="章节号")
    process_parser.add_argument("--data", required=True, help="JSON 格式的处理结果")

    args = parser.parse_args()

    # 初始化
    config = None
    if args.project_root:
        from .config import DataModulesConfig
        config = DataModulesConfig.from_project_root(args.project_root)

    manager = StateManager(config)

    if args.command == "get-progress":
        print(json.dumps(manager._state.get("progress", {}), ensure_ascii=False, indent=2))

    elif args.command == "get-entity":
        entity = manager.get_entity(args.id)
        if entity:
            print(json.dumps(entity, ensure_ascii=False, indent=2))
        else:
            print(f"未找到实体: {args.id}")

    elif args.command == "list-entities":
        if args.type:
            entities = manager.get_entities_by_type(args.type)
        elif args.tier:
            entities = manager.get_entities_by_tier(args.tier)
        else:
            entities = manager.get_all_entities()

        for eid, e in entities.items():
            print(f"{eid}: {e.get('name')} ({e.get('type')}/{e.get('tier')})")

    elif args.command == "process-chapter":
        data = json.loads(args.data)
        warnings = manager.process_chapter_result(args.chapter, data)
        manager.save_state()

        print(f"✓ 已处理第 {args.chapter} 章")
        if warnings:
            print("警告:")
            for w in warnings:
                print(f"  - {w}")


if __name__ == "__main__":
    main()
