# webnovel-writer MCP Server
"""
MCP (Model Context Protocol) Server for webnovel-writer

This server exposes webnovel-writer capabilities as MCP tools and resources,
allowing integration with Claude Code and other MCP-compatible clients.

Usage:
    # Start the server
    python -m mcp_server

    # Or via Claude Code config (~/.claude/mcp_servers.json):
    {
        "servers": {
            "webnovel-writer": {
                "command": "python",
                "args": ["-m", "mcp_server"],
                "cwd": "/path/to/webnovel-writer"
            }
        }
    }
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Tool,
        TextContent,
        Resource,
        ResourceTemplate,
    )
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    print("Warning: MCP package not installed. Run: pip install mcp", file=sys.stderr)

from scripts.data_modules.config import get_config, DataModulesConfig
from scripts.data_modules.state_manager import StateManager


def create_server() -> "Server":
    """Create and configure the MCP server"""

    if not MCP_AVAILABLE:
        raise ImportError("MCP package is required. Install with: pip install mcp")

    app = Server("webnovel-writer")

    # ==================== Tools ====================

    @app.list_tools()
    async def list_tools() -> List[Tool]:
        """List available MCP tools"""
        return [
            Tool(
                name="webnovel-init",
                description="初始化网文项目，创建标准目录结构和 state.json",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_root": {
                            "type": "string",
                            "description": "项目根目录路径"
                        },
                        "title": {
                            "type": "string",
                            "description": "小说标题"
                        },
                        "genre": {
                            "type": "string",
                            "description": "题材类型 (玄幻/都市/科幻/历史/武侠等)"
                        },
                        "protagonist_name": {
                            "type": "string",
                            "description": "主角名称"
                        }
                    },
                    "required": ["project_root", "title"]
                }
            ),
            Tool(
                name="webnovel-query",
                description="查询设定集信息（角色/实力/势力/物品/伏笔）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_root": {
                            "type": "string",
                            "description": "项目根目录路径"
                        },
                        "query_type": {
                            "type": "string",
                            "enum": ["character", "power", "faction", "item", "foreshadowing"],
                            "description": "查询类型"
                        },
                        "name": {
                            "type": "string",
                            "description": "要查询的实体名称（可选）"
                        }
                    },
                    "required": ["project_root", "query_type"]
                }
            ),
            Tool(
                name="webnovel-status",
                description="生成项目健康报告（角色活跃度/伏笔超时/节奏分析）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_root": {
                            "type": "string",
                            "description": "项目根目录路径"
                        },
                        "focus": {
                            "type": "string",
                            "enum": ["all", "characters", "foreshadowing", "pacing", "strand"],
                            "description": "分析焦点"
                        }
                    },
                    "required": ["project_root"]
                }
            ),
            Tool(
                name="webnovel-context",
                description="构建章节写作所需的上下文包",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_root": {
                            "type": "string",
                            "description": "项目根目录路径"
                        },
                        "chapter": {
                            "type": "integer",
                            "description": "目标章节号"
                        }
                    },
                    "required": ["project_root", "chapter"]
                }
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle tool calls"""

        if name == "webnovel-init":
            return await _handle_init(arguments)
        elif name == "webnovel-query":
            return await _handle_query(arguments)
        elif name == "webnovel-status":
            return await _handle_status(arguments)
        elif name == "webnovel-context":
            return await _handle_context(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    # ==================== Resources ====================

    @app.list_resources()
    async def list_resources() -> List[Resource]:
        """List available MCP resources"""
        return [
            Resource(
                uri="webnovel://skills/chapter-writing",
                name="章节写作技能",
                description="v5.0 双 Agent 架构的章节写作流程",
                mimeType="text/markdown"
            ),
            Resource(
                uri="webnovel://skills/outline-planning",
                name="大纲规划技能",
                description="卷级大纲规划与章节细化",
                mimeType="text/markdown"
            ),
            Resource(
                uri="webnovel://skills/quality-review",
                name="质量审查技能",
                description="五检查员并行审查系统",
                mimeType="text/markdown"
            ),
            Resource(
                uri="webnovel://references/三大定律",
                name="三大定律",
                description="网文写作反幻觉协议",
                mimeType="text/markdown"
            ),
            Resource(
                uri="webnovel://references/爽点系统",
                name="爽点系统",
                description="Cool-points 策略指南",
                mimeType="text/markdown"
            ),
        ]

    @app.read_resource()
    async def read_resource(uri: str) -> str:
        """Read a resource by URI"""
        base_path = Path(__file__).parent

        resource_map = {
            "webnovel://skills/chapter-writing": "skills/chapter-writing/SKILL.md",
            "webnovel://skills/outline-planning": "skills/outline-planning/SKILL.md",
            "webnovel://skills/quality-review": "skills/quality-review/SKILL.md",
            "webnovel://references/三大定律": "references/三大定律.md",
            "webnovel://references/爽点系统": "references/cool-point-system.md",
        }

        if uri in resource_map:
            file_path = base_path / resource_map[uri]
            if file_path.exists():
                return file_path.read_text(encoding="utf-8")
            return f"Resource file not found: {resource_map[uri]}"

        return f"Unknown resource URI: {uri}"

    return app


# ==================== Tool Handlers ====================

async def _handle_init(args: Dict[str, Any]) -> List["TextContent"]:
    """Handle webnovel-init tool"""
    from scripts.init_project import init_project

    project_root = Path(args["project_root"])
    title = args.get("title", "未命名小说")
    genre = args.get("genre", "玄幻")
    protagonist = args.get("protagonist_name", "主角")

    try:
        result = init_project(
            project_root=project_root,
            title=title,
            genre=genre,
            protagonist_name=protagonist
        )
        return [TextContent(type="text", text=f"✅ 项目初始化成功\n\n{json.dumps(result, ensure_ascii=False, indent=2)}")]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ 初始化失败: {e}")]


async def _handle_query(args: Dict[str, Any]) -> List["TextContent"]:
    """Handle webnovel-query tool"""
    project_root = Path(args["project_root"])
    query_type = args["query_type"]
    name = args.get("name")

    config = DataModulesConfig.from_project_root(project_root)
    manager = StateManager(config)

    type_map = {
        "character": "角色",
        "power": "招式",
        "faction": "势力",
        "item": "物品",
        "foreshadowing": "伏笔"
    }

    entity_type = type_map.get(query_type, "角色")

    if name:
        # 查询特定实体
        entities = manager.get_entities_by_type(entity_type)
        for eid, entity in entities.items():
            if entity.get("canonical_name") == name or name in entity.get("aliases", []):
                return [TextContent(type="text", text=json.dumps(entity, ensure_ascii=False, indent=2))]
        return [TextContent(type="text", text=f"未找到 {entity_type}: {name}")]
    else:
        # 列出所有实体
        entities = manager.get_entities_by_type(entity_type)
        result = [f"## {entity_type}列表 ({len(entities)})\n"]
        for eid, entity in entities.items():
            name = entity.get("canonical_name", eid)
            tier = entity.get("tier", "装饰")
            result.append(f"- **{name}** ({tier}) - {eid}")
        return [TextContent(type="text", text="\n".join(result))]


async def _handle_status(args: Dict[str, Any]) -> List["TextContent"]:
    """Handle webnovel-status tool"""
    from scripts.status_reporter import StatusReporter

    project_root = args["project_root"]
    focus = args.get("focus", "all")

    reporter = StatusReporter(project_root)
    if not reporter.load_state():
        return [TextContent(type="text", text="❌ 无法加载 state.json")]

    reporter.scan_chapters()
    report = reporter.generate_report(focus)

    return [TextContent(type="text", text=report)]


async def _handle_context(args: Dict[str, Any]) -> List["TextContent"]:
    """Handle webnovel-context tool"""
    from scripts.context_pack_builder import ContextPackBuilder

    project_root = Path(args["project_root"])
    chapter = args["chapter"]

    builder = ContextPackBuilder(project_root)
    context_pack = builder.build(chapter)

    return [TextContent(type="text", text=json.dumps(context_pack, ensure_ascii=False, indent=2))]


# ==================== Main Entry ====================

async def main():
    """Main entry point for MCP server"""
    if not MCP_AVAILABLE:
        print("Error: MCP package not installed. Run: pip install mcp", file=sys.stderr)
        sys.exit(1)

    app = create_server()

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
