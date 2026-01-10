#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webnovel-writer 安装脚本

使用方式:
    # 安装为可编辑包（开发模式）
    python install.py --dev

    # 安装为普通包
    python install.py

    # 仅安装依赖
    python install.py --deps-only

    # 安装 MCP 支持
    python install.py --with-mcp

    # 验证安装
    python install.py --verify
"""

import subprocess
import sys
import argparse
from pathlib import Path


def run_command(cmd: list, check: bool = True) -> bool:
    """Run a command and return success status"""
    print(f"$ {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=check, capture_output=False)
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False


def install_deps():
    """Install dependencies from requirements.txt"""
    print("\n📦 Installing dependencies...")
    requirements_file = Path(__file__).parent / "requirements.txt"
    if requirements_file.exists():
        return run_command([sys.executable, "-m", "pip", "install", "-r", str(requirements_file)])
    else:
        print("⚠️  requirements.txt not found, installing core dependencies...")
        return run_command([sys.executable, "-m", "pip", "install", "pypinyin", "filelock", "aiohttp"])


def install_package(dev: bool = False):
    """Install the package"""
    print(f"\n📦 Installing webnovel-writer {'(development mode)' if dev else ''}...")
    project_root = Path(__file__).parent

    if dev:
        return run_command([sys.executable, "-m", "pip", "install", "-e", str(project_root)])
    else:
        return run_command([sys.executable, "-m", "pip", "install", str(project_root)])


def install_mcp():
    """Install MCP support"""
    print("\n📦 Installing MCP support...")
    return run_command([sys.executable, "-m", "pip", "install", "mcp"])


def verify_installation():
    """Verify the installation"""
    print("\n🔍 Verifying installation...")

    checks = []

    # Check imports
    try:
        from scripts.data_modules.config import DataModulesConfig
        checks.append(("✅", "data_modules.config"))
    except ImportError as e:
        checks.append(("❌", f"data_modules.config: {e}"))

    try:
        from scripts.data_modules.state_manager import StateManager
        checks.append(("✅", "data_modules.state_manager"))
    except ImportError as e:
        checks.append(("❌", f"data_modules.state_manager: {e}"))

    try:
        from scripts.context_pack_builder import ContextPackBuilder
        checks.append(("✅", "context_pack_builder"))
    except ImportError as e:
        checks.append(("❌", f"context_pack_builder: {e}"))

    try:
        from scripts.status_reporter import StatusReporter
        checks.append(("✅", "status_reporter"))
    except ImportError as e:
        checks.append(("❌", f"status_reporter: {e}"))

    # Check MCP
    try:
        import mcp
        checks.append(("✅", "MCP support"))
    except ImportError:
        checks.append(("⚠️ ", "MCP support (optional, install with --with-mcp)"))

    # Print results
    print("\n📋 Installation check results:")
    all_passed = True
    for status, name in checks:
        print(f"  {status} {name}")
        if status == "❌":
            all_passed = False

    return all_passed


def print_usage():
    """Print usage instructions after installation"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║              webnovel-writer 安装成功！                        ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  使用方式:                                                    ║
║                                                              ║
║  1. Claude Code 插件模式:                                     ║
║     在项目目录中使用 /webnovel-* 命令                           ║
║                                                              ║
║  2. MCP Server 模式:                                         ║
║     python -m mcp_server                                     ║
║                                                              ║
║  3. 命令行工具:                                               ║
║     webnovel-init      # 初始化项目                           ║
║     webnovel-status    # 生成健康报告                          ║
║     webnovel-context   # 构建上下文包                          ║
║                                                              ║
║  4. Python API:                                              ║
║     from scripts.data_modules import StateManager             ║
║     from scripts.context_pack_builder import ContextPackBuilder║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


def main():
    parser = argparse.ArgumentParser(description="webnovel-writer 安装脚本")
    parser.add_argument("--dev", action="store_true", help="开发模式安装（可编辑）")
    parser.add_argument("--deps-only", action="store_true", help="仅安装依赖")
    parser.add_argument("--with-mcp", action="store_true", help="安装 MCP 支持")
    parser.add_argument("--verify", action="store_true", help="验证安装")

    args = parser.parse_args()

    print("=" * 60)
    print("🖊️  webnovel-writer v5.0.0 安装程序")
    print("=" * 60)

    if args.verify:
        success = verify_installation()
        sys.exit(0 if success else 1)

    # Install dependencies
    if not install_deps():
        print("❌ 依赖安装失败")
        sys.exit(1)

    # Install MCP if requested
    if args.with_mcp:
        if not install_mcp():
            print("⚠️  MCP 安装失败，但核心功能仍可用")

    # Install package
    if not args.deps_only:
        if not install_package(dev=args.dev):
            print("❌ 包安装失败")
            sys.exit(1)

    # Verify
    if verify_installation():
        print_usage()
        print("✅ 安装完成！")
    else:
        print("⚠️  安装完成，但部分检查未通过")


if __name__ == "__main__":
    main()
