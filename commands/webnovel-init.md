---
description: 初始化网文项目，创建设定集、大纲框架和 state.json
argument-hint: [项目目录]（可选，默认 ./webnovel-project）
allowed-tools: Read, Write, Edit, Bash, AskUserQuestion
---

# /webnovel-init

初始化一个新的网文写作项目。

## 执行流程

1. **交互式设定**：通过问答确定题材、标题、主角、金手指（建议按 `project-init` Skill 执行）

2. **生成项目结构（唯一入口）**
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/init_project.py" "./webnovel-project" "{小说标题}" "{题材}" \
     --protagonist-name "{主角姓名}" \
     --golden-finger-name "{系统名}" \
     --golden-finger-type "{系统类型}" \
     --core-selling-points "{卖点1,卖点2}"
   ```

3. **生成文件**（在项目目录下）：
   - `.webnovel/state.json` - 项目状态
   - `设定集/` - 角色、势力、功法等
   - `大纲/总纲.md` - 剧情框架
   - `正文/` - 章节目录

4. **版本控制**：脚本会在项目目录初始化 Git（如未安装 Git 则跳过）

## 参考 Skill

详细流程见 `project-init` Skill。
