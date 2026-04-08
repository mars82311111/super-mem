#!/bin/bash
# SuperMem 一键安装脚本
# ============================
# 支持 macOS / Linux
# 依赖: Python 3.9+, Git, pip

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
INSTALL_DIR="${HOME}/.super-mem"
WORKSPACE_DIR="${HOME}/.openclaw/workspace"
OPENCLAW_HOOKS_DIR="${HOME}/.openclaw/hooks"
OPENCLAW_SKILLS_DIR="${HOME}/.openclaw/workspace/skills"
MEMPALACE_CLI="/usr/bin/python3"

echo "=========================================="
echo "  SuperMem 安装程序"
echo "  MemPalace + SM6 精华融合记忆系统"
echo "=========================================="
echo ""

# 1. 检查依赖
echo "📋 检查依赖..."
command -v git >/dev/null 2>&1 || { echo "${RED}❌ git 未安装${NC}"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "${RED}❌ python3 未安装${NC}"; exit 1; }

# 2. 创建目录
echo "📁 创建目录..."
mkdir -p "${INSTALL_DIR}"
mkdir -p "${OPENCLAW_HOOKS_DIR}"
mkdir -p "${OPENCLAW_SKILLS_DIR}"

# 3. 复制文件
echo "📦 复制文件..."
REPO_DIR="$(cd "$(dirname "$0")" && pwd)/.."
cp -r "${REPO_DIR}/scripts" "${INSTALL_DIR}/"
cp -r "${REPO_DIR}/skills" "${INSTALL_DIR}/"
cp -r "${REPO_DIR}/hooks" "${INSTALL_DIR}/"
echo "✅ 文件复制完成"

# 4. 安装 Python 依赖
echo "🐍 安装 Python 依赖..."
${MEMPALACE_CLI} -m pip install mempalace --quiet 2>/dev/null || ${MEMPALACE_CLI} -m pip install mempalace
${MEMPALACE_CLI} -m pip install chromadb --quiet 2>/dev/null || ${MEMPALACE_CLI} -m pip install chromadb
echo "✅ Python 依赖安装完成"

# 5. 初始化 MemPalace
echo "🧠 初始化 MemPalace..."
if [ -d "${WORKSPACE_DIR}" ]; then
    printf '\n\n\n' | ${MEMPALACE_CLI} -m mempalace init "${WORKSPACE_DIR}" 2>/dev/null || true
    echo "✅ MemPalace 初始化完成"
else
    mkdir -p "${WORKSPACE_DIR}"
    printf '\n\n\n' | ${MEMPALACE_CLI} -m mempalace init "${WORKSPACE_DIR}" 2>/dev/null || true
    echo "✅ MemPalace 初始化完成"
fi

# 6. 挖掘 workspace
echo "⛏️  挖掘 workspace..."
${MEMPALACE_CLI} -m mempalace mine "${WORKSPACE_DIR}" --mode projects >/dev/null 2>&1 || true
echo "✅ Workspace 挖掘完成"

# 7. 链接 Hook 到 OpenClaw
echo "🔗 配置 OpenClaw Hook..."
mkdir -p "${OPENCLAW_HOOKS_DIR}/mempalace-recall"
cp -r "${INSTALL_DIR}/hooks/mempalace-recall/"* "${OPENCLAW_HOOKS_DIR}/mempalace-recall/"
echo "✅ Hook 配置完成"

# 8. 链接 Skill 到 OpenClaw
echo "📚 配置 OpenClaw Skill..."
cp -r "${INSTALL_DIR}/skills/mempalace-memory" "${OPENCLAW_SKILLS_DIR}/"
echo "✅ Skill 配置完成"

# 9. 验证安装
echo ""
echo "🔍 验证安装..."
STATUS=$(${MEMPALACE_CLI} "${INSTALL_DIR}/scripts/super_mem_cli.py" status 2>/dev/null)
if echo "$STATUS" | grep -q '"status"'; then
    echo "${GREEN}✅ SuperMem 安装成功！${NC}"
else
    echo "${YELLOW}⚠️  安装完成但验证未通过，请手动检查${NC}"
fi

# 10. 提示用户重启 OpenClaw
echo ""
echo "=========================================="
echo "${GREEN}✅ 安装完成！${NC}"
echo ""
echo "下一步："
echo "1. 重启 OpenClaw Gateway:"
echo "   openclaw gateway restart"
echo ""
echo "2. 验证 Hook 已启用:"
echo "   openclaw hooks list"
echo ""
echo "3. 测试搜索:"
echo "   ${MEMPALACE_CLI} ${INSTALL_DIR}/scripts/super_mem_cli.py search \"hello\""
echo "=========================================="
