#!/usr/bin/env python3
"""
工作流状态管理器
- 追踪命令执行状态
- 检测中断点
- 提供恢复策略
"""

import json
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# ============================================================================
# 安全修复：导入安全工具函数（P1 MEDIUM）
# ============================================================================
from security_utils import create_secure_directory, atomic_write_json
from project_locator import resolve_project_root
from chapter_paths import default_chapter_draft_path, find_chapter_file

# UTF-8 编码修复（Windows兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def find_project_root():
    """解析项目根目录（包含 .webnovel/state.json）"""
    return resolve_project_root()

def get_workflow_state_path():
    """获取 workflow_state.json 的完整路径"""
    project_root = find_project_root()
    return project_root / '.webnovel' / 'workflow_state.json'

def start_task(command, args):
    """开始新任务"""
    state = load_state()
    state['current_task'] = {
        'command': command,
        'args': args,
        'started_at': datetime.now().isoformat(),
        'last_heartbeat': datetime.now().isoformat(),
        'status': 'running',
        'current_step': None,
        'completed_steps': [],
        'pending_steps': get_pending_steps(command),
        'artifacts': {
            'chapter_file': {},
            'git_status': {},
            'state_json_modified': False,
            'entities_extracted': False,
            'review_completed': False
        }
    }
    save_state(state)
    print(f"✅ 任务已启动: {command} {json.dumps(args, ensure_ascii=False)}")

def start_step(step_id, step_name, progress_note=None):
    """标记Step开始"""
    state = load_state()
    if not state.get('current_task'):
        print("⚠️ 无活动任务，请先使用 start-task")
        return

    state['current_task']['current_step'] = {
        'id': step_id,
        'name': step_name,
        'status': 'in_progress',
        'started_at': datetime.now().isoformat(),
        'progress_note': progress_note
    }
    state['current_task']['last_heartbeat'] = datetime.now().isoformat()
    save_state(state)
    print(f"▶️  {step_id} 开始: {step_name}")

def complete_step(step_id, artifacts_json=None):
    """标记Step完成"""
    state = load_state()
    if not state.get('current_task') or not state['current_task'].get('current_step'):
        print("⚠️ 无活动Step")
        return

    current_step = state['current_task']['current_step']
    current_step['status'] = 'completed'
    current_step['completed_at'] = datetime.now().isoformat()

    if artifacts_json:
        try:
            artifacts = json.loads(artifacts_json)
            current_step['artifacts'] = artifacts
            # 更新task级别的artifacts
            state['current_task']['artifacts'].update(artifacts)
        except json.JSONDecodeError as e:
            print(f"⚠️ Artifacts JSON解析失败: {e}")

    state['current_task']['completed_steps'].append(current_step)
    state['current_task']['current_step'] = None
    state['current_task']['last_heartbeat'] = datetime.now().isoformat()
    save_state(state)
    print(f"✅ {step_id} 完成")

def complete_task(final_artifacts_json=None):
    """标记任务完成"""
    state = load_state()
    if not state.get('current_task'):
        print("⚠️ 无活动任务")
        return

    state['current_task']['status'] = 'completed'
    state['current_task']['completed_at'] = datetime.now().isoformat()

    if final_artifacts_json:
        try:
            final_artifacts = json.loads(final_artifacts_json)
            state['current_task']['artifacts'].update(final_artifacts)
        except json.JSONDecodeError as e:
            print(f"⚠️ Final artifacts JSON解析失败: {e}")

    # 保存到历史记录
    state['last_stable_state'] = extract_stable_state(state['current_task'])
    if 'history' not in state:
        state['history'] = []
    state['history'].append({
        'task_id': f"task_{len(state['history']) + 1:03d}",
        'command': state['current_task']['command'],
        'chapter': state['current_task']['args'].get('chapter_num'),
        'status': 'completed',
        'completed_at': state['current_task']['completed_at']
    })

    # 清除当前任务
    state['current_task'] = None
    save_state(state)
    print(f"🎉 任务完成")

def detect_interruption():
    """检测中断状态"""
    state = load_state()
    if not state or 'current_task' not in state or state['current_task'] is None:
        return None  # 无中断任务

    task = state['current_task']
    if task['status'] == 'completed':
        return None  # 任务已完成

    # 判断中断原因
    last_heartbeat = datetime.fromisoformat(task['last_heartbeat'])
    elapsed = (datetime.now() - last_heartbeat).total_seconds()

    interrupt_info = {
        'command': task['command'],
        'args': task['args'],
        'current_step': task['current_step'],
        'completed_steps': task['completed_steps'],
        'elapsed_seconds': elapsed,
        'artifacts': task['artifacts'],
        'started_at': task['started_at']
    }

    return interrupt_info

def analyze_recovery_options(interrupt_info):
    """分析恢复选项（基于中断点）"""
    current_step = interrupt_info['current_step']
    command = interrupt_info['command']
    chapter_num = interrupt_info['args'].get('chapter_num', '?')

    if not current_step:
        # 任务刚开始就中断
        return [{
            'option': 'A',
            'label': '从头开始',
            'risk': 'low',
            'description': '重新执行完整流程',
            'actions': [
                f"删除 workflow_state.json 当前任务",
                f"执行 /{command} {chapter_num}"
            ]
        }]

    step_id = current_step['id']

    # 基于Step ID的恢复策略
    if step_id == 'Step 1':
        # Step 1中断：无副作用
        return [{
            'option': 'A',
            'label': '从Step 1重新开始',
            'risk': 'low',
            'description': '重新加载上下文',
            'actions': [
                f"清理中断状态",
                f"执行 /{command} {chapter_num}"
            ]
        }]

    elif step_id == 'Step 2':
        # Step 2中断：可能有半成品文件
        chapter_file = interrupt_info['artifacts'].get('chapter_file', {})

        # 使用 chapter_paths 模块定位章节文件（兼容新旧目录结构）
        project_root = find_project_root()
        existing_chapter = find_chapter_file(project_root, chapter_num)
        draft_path = None
        if existing_chapter:
            chapter_path = str(existing_chapter.relative_to(project_root))
        else:
            # 如果不存在，使用新格式的默认路径
            draft_path = default_chapter_draft_path(project_root, chapter_num)
            chapter_path = str(draft_path.relative_to(project_root))

        options = [{
            'option': 'A',
            'label': '删除半成品，从Step 1重新开始',
            'risk': 'low',
            'description': f"清理 {chapter_path}，重新生成章节",
            'actions': [
                f"删除 {chapter_path}（如存在）",
                f"清理 Git 暂存区",
                f"清理中断状态",
                f"执行 /{command} {chapter_num}"
            ]
        }]

        # 检查文件是否存在
        candidate = existing_chapter or draft_path
        if candidate and candidate.exists():
            options.append({
                'option': 'B',
                'label': '回滚到上一章',
                'risk': 'medium',
                'description': '丢弃所有当前章节进度',
                'actions': [
                    f"git reset --hard ch{(chapter_num-1):04d}",
                    f"清理中断状态",
                    "重新决定是否继续Ch{chapter_num}"
                ]
            })

        return options

    elif step_id == 'Step 2.5':
        # Step 2.5中断：润色中（正文已生成，可能部分改写）
        project_root = find_project_root()
        existing_chapter = find_chapter_file(project_root, chapter_num)
        draft_path = None
        if existing_chapter:
            chapter_path = str(existing_chapter.relative_to(project_root))
        else:
            draft_path = default_chapter_draft_path(project_root, chapter_num)
            chapter_path = str(draft_path.relative_to(project_root))

        options = [{
            'option': 'A',
            'label': '基于现有文件继续润色',
            'risk': 'low',
            'description': f"继续润色 {chapter_path}，完成后进入Step 3",
            'actions': [
                f"打开并继续润色 {chapter_path}",
                "保存文件",
                "继续Step 3（Extract Entities）"
            ]
        }]

        candidate = existing_chapter or draft_path
        if candidate and candidate.exists():
            options.append({
                'option': 'B',
                'label': '删除润色稿，从Step 2重写',
                'risk': 'medium',
                'description': f"删除 {chapter_path}，重新生成章节内容",
                'actions': [
                    f"删除 {chapter_path}",
                    "清理 Git 暂存区",
                    "清理中断状态",
                    f"执行 /{command} {chapter_num}"
                ]
            })

        return options

    elif step_id in ['Step 3', 'Step 5']:
        # Step 3/5中断：脚本未执行完
        return [{
            'option': 'A',
            'label': f'从{step_id}重新开始',
            'risk': 'low',
            'description': '重新运行脚本（幂等操作）',
            'actions': [
                f"重新执行脚本",
                f"继续后续Step"
            ]
        }]

    elif step_id == 'Step 4':
        # Step 4中断：state.json可能部分更新
        return [
            {
                'option': 'A',
                'label': '检查并修复state.json',
                'risk': 'medium',
                'description': '验证state.json一致性，补全缺失字段',
                'actions': [
                    "读取 state.json",
                    "检查必要字段（progress, protagonist_state等）",
                    "如缺失则从前一章推断",
                    "重新执行 update_state.py",
                    "继续Step 5"
                ]
            },
            {
                'option': 'B',
                'label': '回滚到上一章',
                'risk': 'high',
                'description': '恢复到上一章的state.json快照',
                'actions': [
                    f"git checkout ch{(chapter_num-1):04d} -- .webnovel/state.json",
                    f"删除第{chapter_num}章文件",
                    "清理中断状态"
                ]
            }
        ]

    elif step_id == 'Step 7':
        # Step 7中断：Git未提交
        return [
            {
                'option': 'A',
                'label': '继续Git提交',
                'risk': 'low',
                'description': '完成未完成的Git commit + tag',
                'actions': [
                    "检查 Git 暂存区",
                    "重新执行 backup_manager.py",
                    "继续完成工作流追踪（complete-task）"
                ]
            },
            {
                'option': 'B',
                'label': '回滚Git改动',
                'risk': 'medium',
                'description': '丢弃暂存区所有改动',
                'actions': [
                    "git reset HEAD .",
                    f"删除第{chapter_num}章文件",
                    "清理中断状态"
                ]
            }
        ]

    elif step_id == 'Step 6':
        # Step 6中断：审查未完成
        return [
            {
                'option': 'A',
                'label': '重新执行双章审查',
                'risk': 'high',
                'description': '重新调用5个审查员（成本高，耗时长）',
                'actions': [
                    "重新调用5个审查员（并行）",
                    "生成审查报告",
                    "更新 state.json review_checkpoints"
                ]
            },
            {
                'option': 'B',
                'label': '跳过审查，继续下一章',
                'risk': 'medium',
                'description': '不进行审查（可后续用 /webnovel-review 补审）',
                'actions': [
                    "标记审查为已跳过",
                    "清理中断状态",
                    "可继续创作下一章"
                ]
            }
        ]

    # 默认选项
    return [{
        'option': 'A',
        'label': '从头开始',
        'risk': 'low',
        'description': '重新执行完整流程',
        'actions': [
            f"清理所有中断artifacts",
            f"执行 /{command} {chapter_num}"
        ]
    }]

def cleanup_artifacts(chapter_num):
    """清理半成品artifacts"""
    artifacts_cleaned = []

    project_root = find_project_root()

    # 删除章节文件（兼容多种命名/目录结构）
    chapter_path = find_chapter_file(project_root, chapter_num)
    if chapter_path is None:
        # 可能是“草稿路径”但尚未重命名
        draft_path = default_chapter_draft_path(project_root, chapter_num)
        if draft_path.exists():
            chapter_path = draft_path

    if chapter_path and chapter_path.exists():
        chapter_path.unlink()
        artifacts_cleaned.append(str(chapter_path.relative_to(project_root)))

    # 清理Git暂存区
    result = subprocess.run(
        ['git', 'reset', 'HEAD', '.'],
        cwd=project_root,
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        artifacts_cleaned.append("Git暂存区已清理（project）")

    return artifacts_cleaned

def clear_current_task():
    """清除当前中断任务"""
    state = load_state()
    if state.get('current_task'):
        state['current_task'] = None
        save_state(state)
        print("✅ 中断任务已清除")
    else:
        print("⚠️ 无中断任务")

def load_state():
    """加载workflow状态"""
    state_file = get_workflow_state_path()
    if not state_file.exists():
        return {'current_task': None, 'last_stable_state': None, 'history': []}
    with open(state_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_state(state):
    """保存workflow状态（原子化写入）"""
    state_file = get_workflow_state_path()
    # ============================================================================
    # 安全修复：使用原子化写入（P1 MEDIUM）
    # ============================================================================
    create_secure_directory(str(state_file.parent))
    atomic_write_json(state_file, state, use_lock=True, backup=False)

def get_pending_steps(command):
    """获取待执行步骤列表"""
    if command == 'webnovel-write':
        return ['Step 1', 'Step 2', 'Step 2.5', 'Step 3', 'Step 4', 'Step 5', 'Step 6', 'Step 7']
    elif command == 'webnovel-review':
        return ['Step 1', 'Step 2', 'Step 3', 'Step 4', 'Step 5', 'Step 6', 'Step 7', 'Step 8']
    # 其他命令...
    return []

def extract_stable_state(task):
    """提取稳定状态快照"""
    return {
        'command': task['command'],
        'chapter_num': task['args'].get('chapter_num'),
        'completed_at': task.get('completed_at'),
        'artifacts': task.get('artifacts', {})
    }

# CLI接口
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='工作流状态管理')
    subparsers = parser.add_subparsers(dest='action', help='操作类型')

    # start-task
    p_start_task = subparsers.add_parser('start-task', help='开始新任务')
    p_start_task.add_argument('--command', required=True, help='命令名称')
    p_start_task.add_argument('--chapter', type=int, help='章节号')

    # start-step
    p_start_step = subparsers.add_parser('start-step', help='开始Step')
    p_start_step.add_argument('--step-id', required=True, help='Step ID')
    p_start_step.add_argument('--step-name', required=True, help='Step名称')
    p_start_step.add_argument('--note', help='进度备注')

    # complete-step
    p_complete_step = subparsers.add_parser('complete-step', help='完成Step')
    p_complete_step.add_argument('--step-id', required=True, help='Step ID')
    p_complete_step.add_argument('--artifacts', help='Artifacts JSON')

    # complete-task
    p_complete_task = subparsers.add_parser('complete-task', help='完成任务')
    p_complete_task.add_argument('--artifacts', help='Final artifacts JSON')

    # detect
    subparsers.add_parser('detect', help='检测中断')

    # cleanup
    p_cleanup = subparsers.add_parser('cleanup', help='清理artifacts')
    p_cleanup.add_argument('--chapter', type=int, required=True, help='章节号')

    # clear
    subparsers.add_parser('clear', help='清除中断任务')

    args = parser.parse_args()

    if args.action == 'start-task':
        start_task(args.command, {'chapter_num': args.chapter})
    elif args.action == 'start-step':
        start_step(args.step_id, args.step_name, args.note)
    elif args.action == 'complete-step':
        complete_step(args.step_id, args.artifacts)
    elif args.action == 'complete-task':
        complete_task(args.artifacts)
    elif args.action == 'detect':
        interrupt = detect_interruption()
        if interrupt:
            print("\n🔴 检测到中断任务:")
            print(json.dumps(interrupt, ensure_ascii=False, indent=2))
            print("\n💡 恢复选项:")
            options = analyze_recovery_options(interrupt)
            print(json.dumps(options, ensure_ascii=False, indent=2))
        else:
            print("✅ 无中断任务")
    elif args.action == 'cleanup':
        cleaned = cleanup_artifacts(args.chapter)
        print(f"✅ 已清理: {', '.join(cleaned)}")
    elif args.action == 'clear':
        clear_current_task()
    else:
        parser.print_help()
