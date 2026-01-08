#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entity Linker - 实体消歧辅助模块

为 Data Agent 提供实体消歧的辅助功能：
- 置信度判断
- 别名索引管理
- 消歧结果记录
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from .config import get_config


@dataclass
class DisambiguationResult:
    """消歧结果"""
    mention: str
    entity_id: Optional[str]
    confidence: float
    candidates: List[str] = field(default_factory=list)
    adopted: bool = False
    warning: Optional[str] = None


class EntityLinker:
    """实体链接器 - 辅助 Data Agent 进行实体消歧"""

    def __init__(self, config=None):
        self.config = config or get_config()
        self._alias_index: Dict[str, str] = {}
        self._load_alias_index()

    def _load_alias_index(self):
        """加载别名索引"""
        if self.config.alias_index_file.exists():
            with open(self.config.alias_index_file, "r", encoding="utf-8") as f:
                self._alias_index = json.load(f)

    def save_alias_index(self):
        """保存别名索引"""
        self.config.ensure_dirs()
        with open(self.config.alias_index_file, "w", encoding="utf-8") as f:
            json.dump(self._alias_index, f, ensure_ascii=False, indent=2)

    # ==================== 别名管理 ====================

    def register_alias(self, entity_id: str, alias: str) -> bool:
        """注册新别名"""
        if alias in self._alias_index:
            existing = self._alias_index[alias]
            if existing != entity_id:
                return False  # 别名冲突
        self._alias_index[alias] = entity_id
        return True

    def lookup_alias(self, mention: str) -> Optional[str]:
        """查找别名对应的实体ID"""
        return self._alias_index.get(mention)

    def get_all_aliases(self, entity_id: str) -> List[str]:
        """获取实体的所有别名"""
        return [alias for alias, eid in self._alias_index.items() if eid == entity_id]

    # ==================== 置信度判断 ====================

    def evaluate_confidence(self, confidence: float) -> Tuple[str, bool, Optional[str]]:
        """
        评估置信度，返回 (action, adopt, warning)

        - action: "auto" | "warn" | "manual"
        - adopt: 是否采用
        - warning: 警告信息
        """
        if confidence >= self.config.extraction_confidence_high:
            return ("auto", True, None)
        elif confidence >= self.config.extraction_confidence_medium:
            return ("warn", True, f"中置信度匹配 (confidence: {confidence:.2f})")
        else:
            return ("manual", False, f"需人工确认 (confidence: {confidence:.2f})")

    def process_uncertain(
        self,
        mention: str,
        candidates: List[str],
        suggested: str,
        confidence: float,
        context: str = ""
    ) -> DisambiguationResult:
        """
        处理不确定的实体匹配

        返回消歧结果，包含是否采用、警告信息等
        """
        action, adopt, warning = self.evaluate_confidence(confidence)

        result = DisambiguationResult(
            mention=mention,
            entity_id=suggested if adopt else None,
            confidence=confidence,
            candidates=candidates,
            adopted=adopt,
            warning=warning
        )

        return result

    # ==================== 批量处理 ====================

    def process_extraction_result(
        self,
        uncertain_items: List[Dict]
    ) -> Tuple[List[DisambiguationResult], List[str]]:
        """
        处理 AI 提取结果中的 uncertain 项

        返回 (results, warnings)
        """
        results = []
        warnings = []

        for item in uncertain_items:
            result = self.process_uncertain(
                mention=item.get("mention", ""),
                candidates=item.get("candidates", []),
                suggested=item.get("suggested", ""),
                confidence=item.get("confidence", 0.0),
                context=item.get("context", "")
            )
            results.append(result)

            if result.warning:
                warnings.append(f"{result.mention} → {result.entity_id}: {result.warning}")

        return results, warnings

    def register_new_entities(
        self,
        new_entities: List[Dict]
    ) -> List[str]:
        """
        注册新实体的别名

        返回注册的实体ID列表
        """
        registered = []

        for entity in new_entities:
            entity_id = entity.get("suggested_id") or entity.get("id")
            if not entity_id or entity_id == "NEW":
                continue

            # 注册主名称
            name = entity.get("name", "")
            if name:
                self.register_alias(entity_id, name)

            # 注册提及方式
            for mention in entity.get("mentions", []):
                if mention and mention != name:
                    self.register_alias(entity_id, mention)

            registered.append(entity_id)

        return registered


# ==================== CLI 接口 ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Entity Linker CLI")
    parser.add_argument("--project-root", type=str, help="项目根目录")

    subparsers = parser.add_subparsers(dest="command")

    # 注册别名
    register_parser = subparsers.add_parser("register-alias")
    register_parser.add_argument("--entity", required=True, help="实体ID")
    register_parser.add_argument("--alias", required=True, help="别名")

    # 查找别名
    lookup_parser = subparsers.add_parser("lookup")
    lookup_parser.add_argument("--mention", required=True, help="提及文本")

    # 列出别名
    list_parser = subparsers.add_parser("list-aliases")
    list_parser.add_argument("--entity", required=True, help="实体ID")

    args = parser.parse_args()

    # 初始化
    config = None
    if args.project_root:
        from .config import DataModulesConfig
        config = DataModulesConfig.from_project_root(args.project_root)

    linker = EntityLinker(config)

    if args.command == "register-alias":
        success = linker.register_alias(args.entity, args.alias)
        if success:
            linker.save_alias_index()
            print(f"✓ 已注册: {args.alias} → {args.entity}")
        else:
            existing = linker.lookup_alias(args.alias)
            print(f"✗ 别名冲突: {args.alias} 已绑定到 {existing}")

    elif args.command == "lookup":
        entity_id = linker.lookup_alias(args.mention)
        if entity_id:
            print(f"{args.mention} → {entity_id}")
        else:
            print(f"未找到: {args.mention}")

    elif args.command == "list-aliases":
        aliases = linker.get_all_aliases(args.entity)
        if aliases:
            print(f"{args.entity} 的别名:")
            for alias in aliases:
                print(f"  - {alias}")
        else:
            print(f"未找到 {args.entity} 的别名")


if __name__ == "__main__":
    main()
