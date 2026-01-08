#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章节创作 Token 预算分析

分析每章创作的 token 消耗：
1. 输入上下文（参考文件 + Context Pack）
2. 输出生成（章节正文 + 标签 + 摘要）
3. 审查子代理消耗

Token 估算规则（中文）：
- 1 个中文字符 ≈ 1.5-2 tokens
- 1 个英文单词 ≈ 1-1.5 tokens
- 保守估计：1 中文字 ≈ 2 tokens
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple

# Windows 编码修复
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


# ============================================================================
# Token 估算函数
# ============================================================================

def estimate_tokens(text: str) -> int:
    """估算文本的 token 数（中文约 2 tokens/字，英文约 1.3 tokens/word）"""
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    # 中文：2 tokens/字，其他：0.3 tokens/字符（粗略）
    return int(chinese_chars * 2 + other_chars * 0.3)


def get_file_tokens(file_path: Path) -> Tuple[int, int]:
    """获取文件的字符数和估算 token 数"""
    if not file_path.exists():
        return 0, 0
    try:
        content = file_path.read_text(encoding='utf-8')
        return len(content), estimate_tokens(content)
    except Exception:
        return 0, 0


# ============================================================================
# 上下文文件清单
# ============================================================================

def analyze_context_files(plugin_root: Path) -> Dict[str, Dict]:
    """分析所有上下文文件的 token 消耗"""

    files = {
        # Step 1: 核心约束（必须加载）
        "core-constraints.md": {
            "path": plugin_root / "skills" / "chapter-writing" / "references" / "core-constraints.md",
            "category": "必须加载",
            "frequency": "每章",
        },

        # Step 3: 场景参考（按需加载）
        "combat-scenes.md": {
            "path": plugin_root / "skills" / "chapter-writing" / "references" / "writing" / "combat-scenes.md",
            "category": "按需加载",
            "frequency": "战斗章节（约30%）",
        },
        "emotion-psychology.md": {
            "path": plugin_root / "skills" / "chapter-writing" / "references" / "writing" / "emotion-psychology.md",
            "category": "按需加载",
            "frequency": "情感章节（约20%）",
        },
        "dialogue-writing.md": {
            "path": plugin_root / "skills" / "chapter-writing" / "references" / "writing" / "dialogue-writing.md",
            "category": "按需加载",
            "frequency": "对话密集章节（约40%）",
        },
        "scene-description.md": {
            "path": plugin_root / "skills" / "chapter-writing" / "references" / "writing" / "scene-description.md",
            "category": "按需加载",
            "frequency": "复杂场景（约15%）",
        },

        # Step 3.5: 题材专项（首次加载）
        "xuanhuan-cultivation.md": {
            "path": plugin_root / "genres" / "xuanhuan" / "cultivation-levels.md",
            "category": "首次加载",
            "frequency": "玄幻题材首章",
        },
        "xuanhuan-power.md": {
            "path": plugin_root / "genres" / "xuanhuan" / "power-systems.md",
            "category": "首次加载",
            "frequency": "玄幻题材首章",
        },
        "xuanhuan-cool-points.md": {
            "path": plugin_root / "genres" / "xuanhuan" / "xuanhuan-cool-points.md",
            "category": "首次加载",
            "frequency": "玄幻题材首章",
        },

        # 润色指南
        "polish-guide.md": {
            "path": plugin_root / "skills" / "chapter-writing" / "references" / "polish-guide.md",
            "category": "按需加载",
            "frequency": "需要润色时（约50%）",
        },
    }

    results = {}
    for name, info in files.items():
        chars, tokens = get_file_tokens(info["path"])
        results[name] = {
            "chars": chars,
            "tokens": tokens,
            "category": info["category"],
            "frequency": info["frequency"],
            "exists": info["path"].exists(),
        }

    return results


def analyze_context_pack(chapter: int = 100) -> Dict:
    """分析 Context Pack 的典型大小"""

    # 基于 500 章模拟数据估算
    # Context Pack 包含：
    # - chapter_outline: 约 200-500 字
    # - protagonist_snapshot: 约 100-300 字
    # - recent_summaries (5章): 约 500-1000 字
    # - location_context: 约 100-200 字
    # - appearing_characters (3-5个): 约 300-600 字
    # - urgent_foreshadowing (0-5个): 约 0-300 字
    # - worldview_skeleton: 约 500-1000 字
    # - power_system_skeleton: 约 300-500 字

    estimates = {
        "chapter_outline": {"chars": 350, "tokens": 700},
        "protagonist_snapshot": {"chars": 200, "tokens": 400},
        "recent_summaries": {"chars": 750, "tokens": 1500},
        "location_context": {"chars": 150, "tokens": 300},
        "appearing_characters": {"chars": 450, "tokens": 900},
        "urgent_foreshadowing": {"chars": 150, "tokens": 300},
        "worldview_skeleton": {"chars": 750, "tokens": 1500},
        "power_system_skeleton": {"chars": 400, "tokens": 800},
    }

    # 随章节增长，摘要和角色会略微增加
    growth_factor = 1 + (chapter / 500) * 0.2  # 500章增长20%

    for key in estimates:
        estimates[key]["tokens"] = int(estimates[key]["tokens"] * growth_factor)

    total_tokens = sum(e["tokens"] for e in estimates.values())

    return {
        "components": estimates,
        "total_tokens": total_tokens,
        "chapter": chapter,
    }


def analyze_output() -> Dict:
    """分析输出 token 消耗"""

    # 章节正文：3000-5000 字
    # 中文字 ≈ 2 tokens
    chapter_content = {
        "min_chars": 3000,
        "max_chars": 5000,
        "avg_chars": 4000,
        "min_tokens": 6000,
        "max_tokens": 10000,
        "avg_tokens": 8000,
    }

    # 章末标签：约 200-500 字
    chapter_tags = {
        "avg_chars": 350,
        "avg_tokens": 700,
    }

    # 章末摘要：约 150-300 字
    chapter_summary = {
        "avg_chars": 200,
        "avg_tokens": 400,
    }

    return {
        "chapter_content": chapter_content,
        "chapter_tags": chapter_tags,
        "chapter_summary": chapter_summary,
        "total_avg_tokens": chapter_content["avg_tokens"] + chapter_tags["avg_tokens"] + chapter_summary["avg_tokens"],
    }


def analyze_review_agents() -> Dict:
    """分析审查子代理的 token 消耗（每2章）"""

    # 5 个审查子代理，每个需要：
    # - 输入：2章正文 + 相关上下文
    # - 输出：审查报告

    agents = {
        "high-point-checker": {
            "input_tokens": 18000,  # 2章正文 + 爽点规范
            "output_tokens": 1500,  # 审查报告
        },
        "consistency-checker": {
            "input_tokens": 20000,  # 2章正文 + 设定集
            "output_tokens": 2000,
        },
        "pacing-checker": {
            "input_tokens": 18000,  # 2章正文 + Strand规范
            "output_tokens": 1500,
        },
        "ooc-checker": {
            "input_tokens": 22000,  # 2章正文 + 角色卡
            "output_tokens": 2000,
        },
        "continuity-checker": {
            "input_tokens": 20000,  # 2章正文 + 伏笔追踪
            "output_tokens": 1500,
        },
    }

    total_input = sum(a["input_tokens"] for a in agents.values())
    total_output = sum(a["output_tokens"] for a in agents.values())

    return {
        "agents": agents,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "per_chapter": (total_input + total_output) / 2,  # 每2章执行一次
    }


def generate_report(plugin_root: Path) -> str:
    """生成完整的 Token 预算报告"""

    lines = [
        "=" * 70,
        "📊 章节创作 Token 预算分析",
        "=" * 70,
        "",
    ]

    # 1. 上下文文件分析
    context_files = analyze_context_files(plugin_root)

    lines.extend([
        "## 1. 参考文件 Token 消耗",
        "",
        "### 必须加载（每章）",
        "| 文件 | 字符数 | Token数 | 说明 |",
        "|------|-------|---------|------|",
    ])

    must_load_total = 0
    for name, info in context_files.items():
        if info["category"] == "必须加载":
            status = "✅" if info["exists"] else "❌"
            lines.append(f"| {name} | {info['chars']:,} | {info['tokens']:,} | {status} |")
            must_load_total += info["tokens"]

    lines.extend([
        f"| **小计** | - | **{must_load_total:,}** | - |",
        "",
        "### 按需加载（场景相关）",
        "| 文件 | Token数 | 触发条件 | 加载概率 |",
        "|------|---------|---------|---------|",
    ])

    optional_files = [(n, i) for n, i in context_files.items() if i["category"] == "按需加载"]
    weighted_optional = 0
    for name, info in optional_files:
        # 解析概率
        freq = info["frequency"]
        prob = 0.3  # 默认
        if "30%" in freq:
            prob = 0.3
        elif "20%" in freq:
            prob = 0.2
        elif "40%" in freq:
            prob = 0.4
        elif "15%" in freq:
            prob = 0.15
        elif "50%" in freq:
            prob = 0.5

        weighted_optional += info["tokens"] * prob
        lines.append(f"| {name} | {info['tokens']:,} | {freq} | {prob*100:.0f}% |")

    lines.append(f"| **加权平均** | **{int(weighted_optional):,}** | - | - |")

    lines.extend([
        "",
        "### 首次加载（题材专项）",
        "| 文件 | Token数 | 说明 |",
        "|------|---------|------|",
    ])

    first_load_total = 0
    for name, info in context_files.items():
        if info["category"] == "首次加载":
            lines.append(f"| {name} | {info['tokens']:,} | 仅首章 |")
            first_load_total += info["tokens"]

    lines.append(f"| **小计** | **{first_load_total:,}** | 摊销到全书 |")

    # 2. Context Pack 分析
    context_pack = analyze_context_pack(100)

    lines.extend([
        "",
        "## 2. Context Pack Token 消耗",
        "",
        "| 组件 | Token数 | 说明 |",
        "|------|---------|------|",
    ])

    for name, data in context_pack["components"].items():
        lines.append(f"| {name} | {data['tokens']:,} | - |")

    lines.append(f"| **合计** | **{context_pack['total_tokens']:,}** | 第100章时 |")

    # 3. 输出分析
    output = analyze_output()

    lines.extend([
        "",
        "## 3. 输出 Token 消耗",
        "",
        "| 组件 | 字符数 | Token数 |",
        "|------|-------|---------|",
        f"| 章节正文 | 3000-5000 | 6000-10000 |",
        f"| 章末标签 | ~350 | ~{output['chapter_tags']['avg_tokens']} |",
        f"| 章末摘要 | ~200 | ~{output['chapter_summary']['avg_tokens']} |",
        f"| **合计** | ~4550 | **~{output['total_avg_tokens']:,}** |",
    ])

    # 4. 审查子代理分析
    review = analyze_review_agents()

    lines.extend([
        "",
        "## 4. 审查子代理 Token 消耗（每2章）",
        "",
        "| 子代理 | 输入 | 输出 | 合计 |",
        "|--------|------|------|------|",
    ])

    for name, data in review["agents"].items():
        total = data["input_tokens"] + data["output_tokens"]
        lines.append(f"| {name} | {data['input_tokens']:,} | {data['output_tokens']:,} | {total:,} |")

    lines.extend([
        f"| **5代理总计** | {review['total_input_tokens']:,} | {review['total_output_tokens']:,} | {review['total_tokens']:,} |",
        f"| **摊销/章** | - | - | **{int(review['per_chapter']):,}** |",
    ])

    # 5. 综合预算
    lines.extend([
        "",
        "=" * 70,
        "## 📋 单章 Token 预算汇总",
        "=" * 70,
        "",
    ])

    # 计算总预算
    input_base = must_load_total + context_pack["total_tokens"]
    input_optional = int(weighted_optional)
    input_total = input_base + input_optional

    output_total = output["total_avg_tokens"]
    review_per_chapter = int(review["per_chapter"])

    grand_total = input_total + output_total + review_per_chapter

    lines.extend([
        "### 输入 Token（上下文加载）",
        f"- 必须加载参考文件: {must_load_total:,}",
        f"- Context Pack: {context_pack['total_tokens']:,}",
        f"- 按需场景参考（加权）: {input_optional:,}",
        f"- **输入小计: {input_total:,}**",
        "",
        "### 输出 Token（内容生成）",
        f"- 章节正文: ~8,000",
        f"- 标签+摘要: ~1,100",
        f"- **输出小计: {output_total:,}**",
        "",
        "### 审查 Token（每章摊销）",
        f"- 5个子代理/2章: {review_per_chapter:,}",
        "",
        "=" * 70,
        f"### 🎯 单章总预算: ~{grand_total:,} tokens",
        "=" * 70,
        "",
    ])

    # 6. 成本估算
    # Claude Sonnet: $3/M input, $15/M output
    # Claude Opus: $15/M input, $75/M output

    sonnet_input_cost = input_total / 1_000_000 * 3
    sonnet_output_cost = (output_total + review_per_chapter) / 1_000_000 * 15
    sonnet_total = sonnet_input_cost + sonnet_output_cost

    opus_input_cost = input_total / 1_000_000 * 15
    opus_output_cost = (output_total + review_per_chapter) / 1_000_000 * 75
    opus_total = opus_input_cost + opus_output_cost

    lines.extend([
        "## 6. 成本估算（API 价格）",
        "",
        "| 模型 | 输入成本 | 输出成本 | 单章成本 | 500章成本 |",
        "|------|---------|---------|---------|----------|",
        f"| Claude Sonnet | ${sonnet_input_cost:.4f} | ${sonnet_output_cost:.4f} | ${sonnet_total:.4f} | ${sonnet_total*500:.2f} |",
        f"| Claude Opus | ${opus_input_cost:.4f} | ${opus_output_cost:.4f} | ${opus_total:.4f} | ${opus_total*500:.2f} |",
        "",
    ])

    # 7. 优化建议
    lines.extend([
        "## 7. 优化建议",
        "",
        "### 高优先级",
        f"- [ ] 摘要压缩：recent_summaries 从5章压缩到3章，节省 ~600 tokens",
        f"- [ ] 骨架精简：worldview/power_system 精简50%，节省 ~1,150 tokens",
        f"- [ ] 审查合并：5个子代理合并为2个，节省 ~50,000 tokens/2章",
        "",
        "### 中优先级",
        f"- [ ] 参考文件缓存：首次加载后缓存到上下文，避免重复传输",
        f"- [ ] 增量 Context Pack：只传输变化部分",
        "",
        "### 低优先级（Claude 4.5 Opus 上下文充足）",
        f"- [ ] 场景参考按需精简",
        f"- [ ] 角色快照压缩",
    ])

    # 8. 500章总预算
    total_500 = grand_total * 500 + first_load_total

    lines.extend([
        "",
        "=" * 70,
        "## 📊 500章总预算",
        "=" * 70,
        "",
        f"- 单章平均: {grand_total:,} tokens",
        f"- 500章总计: {total_500:,} tokens ({total_500/1_000_000:.2f}M)",
        f"- 首次加载题材: {first_load_total:,} tokens（一次性）",
        "",
        f"### 预估成本",
        f"- Claude Sonnet 500章: ~${sonnet_total*500:.2f}",
        f"- Claude Opus 500章: ~${opus_total*500:.2f}",
        "",
    ])

    return "\n".join(lines)


def main():
    # 找到 plugin root
    script_dir = Path(__file__).resolve().parent
    plugin_root = script_dir.parent

    if not (plugin_root / "skills").exists():
        # 尝试当前目录
        plugin_root = Path.cwd()
        if not (plugin_root / "skills").exists():
            plugin_root = Path.cwd().parent

    print(f"📁 Plugin Root: {plugin_root}")
    print()

    report = generate_report(plugin_root)
    print(report)

    # 保存报告
    report_file = script_dir / "token_budget_report.md"
    report_file.write_text(report, encoding="utf-8")
    print(f"\n📄 报告已保存: {report_file}")


if __name__ == "__main__":
    main()
