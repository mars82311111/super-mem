# SuperMem 🧠

> MemPalace + SM6 精华融合 · AI Agent 记忆系统

**22k⭐ MemPalace** 的检索质量 + **SM6** 的工程化增强 = 最强本地记忆系统

[![Stars](https://img.shields.io/github/stars/mars82311111/super-mem)](https://github.com/mars82311111/super-mem)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## ✨ 核心功能

| 功能 | 来源 | 说明 |
|------|------|------|
| **Benchmark 第一检索** | MemPalace | BM25 + 向量混合搜索 |
| **4层记忆栈** | MemPalace | Hot / Warm / Cold / Archive |
| **MMR 多样性重排** | SM6 | 避免单一主题重复 |
| **时间衰减（Temporal Decay）** | SM6 | 近期记忆优先，半衰期30天 |
| **Levenshtein 去重** | SM6 | >85% 相似度不重复记录 |
| **Exact Match 优先** | SM6 | 关键词完整匹配优先级提升 |
| **元数据自动清洗** | SM6 | 去除系统元数据前缀 |
| **Hook 自动注入** | SM6 | `message:preprocessed` 全自动触发 |
| **ChromaDB 删除** | SM6 | 可删除过时记忆 |
| **子系统健康检查** | SM6 | ChromaDB 抽屉状态一览 |
| **完全本地运行** | MemPalace | 无需 API key |

---

## 🚀 一键安装

```bash
# 方法1: 一键安装（推荐）
curl -sSL https://raw.githubusercontent.com/mars82311111/super-mem/main/scripts/install.sh | bash

# 方法2: 手动安装
git clone https://github.com/mars82311111/super-mem.git ~/super-mem
cd ~/super-mem
chmod +x scripts/install.sh
./scripts/install.sh
```

安装脚本会自动：
1. 安装 MemPalace (`pip install mempalace`)
2. 安装 ChromaDB 依赖
3. 初始化记忆系统
4. 配置 OpenClaw Hook（自动记忆注入）
5. 挖掘 workspace

---

## 📖 使用方法

### 增强搜索（默认）
```bash
# 搜索 - 自动应用：时间衰减 + Exact Match 优先 + MMR + 去重
python3 scripts/super_mem_cli.py search "查询内容"

# 指定时间衰减权重（0.0=只看相关性，1.0=只看新旧）
python3 scripts/super_mem_cli.py search "查询" --temporal-weight 0.3

# 设置记忆半衰期（天）
python3 scripts/super_mem_cli.py search "查询" --half-life-days 30

# 关闭 Exact Match 优先
python3 scripts/super_mem_cli.py search "查询" --no-exact-boost

# 关闭 MMR 多样性重排
python3 scripts/super_mem_cli.py search "查询" --no-mmr
```

### 健康检查
```bash
python3 scripts/super_mem_cli.py status
# 返回: 抽屉数、总记忆数、各分类状态
```

### 启动唤醒
```bash
python3 scripts/super_mem_cli.py wake-up
```

### 删除记忆
```bash
python3 scripts/super_mem_cli.py forget <memory_id>
```

### 增量挖掘
```bash
python3 scripts/super_mem_cli.py mine --path /your/workspace
```

---

## 🔧 OpenClaw 集成

### Hook 自动触发（推荐）
安装后 OpenClaw 会自动在每次消息时触发 `mempalace-recall` hook，无需手动 recall。

### 手动触发
在 OpenClaw 对话中直接调用 CLI 工具。

---

## 🏗️ 系统架构

```
消息入口 (message:preprocessed hook)
  ↓
1. strip_metadata() — 清洗元数据
  ↓
2. MemPalace 混合搜索 — BM25 + 向量 + 图遍历
  ↓
3. Exact Match Boost — 关键词完整匹配 ×2.0
  ↓
4. Levenshtein 去重 — >85% 相似度去除
  ↓
5. Temporal Decay — 文件修改时间衰减
  ↓
6. MMR 多样性重排 — 主题多样性保证
  ↓
7. 注入 bodyForAgent → 模型响应
```

---

## 📊 时间衰减机制

```
Score = base_score × (1 - λ) + decay(mtime) × λ

λ = temporal_weight (默认 0.3)
decay = 0.5^(days_elapsed / half_life_days)
half_life_days = 30 (默认)

效果: 30天前记忆的decay分约0.5，权重0.3时对总分影响约15%
```

---

## 📦 目录结构

```
super-mem/
├── scripts/
│   ├── install.sh              # 一键安装脚本
│   └── super_mem_cli.py       # 增强版 CLI（MMR + 去重 + 时间衰减 + Exact优先）
├── skills/
│   └── mempalace-memory/
│       └── SKILL.md          # OpenClaw Skill 说明
├── hooks/
│   └── mempalace-recall/
│       ├── HOOK.md            # Hook 说明
│       └── handler.ts         # TypeScript Hook 实现
└── README.md
```

---

## 🆚 vs 其他记忆系统

| 系统 | Stars | API Key | 时间衰减 | Exact优先 | 自动Hook |
|------|-------|---------|---------|---------|---------|
| **SuperMem** | - | ❌ 不需要 | ✅ | ✅ | ✅ |
| OpenViking | 21k | ⚠️ 需要 | ❌ | ❌ | ❌ |
| MemPalace | 22k | ❌ 不需要 | ❌ | ❌ | ❌ |
| SM6 | - | ⚠️ 需要 | ✅ | ✅ | ❌ (不稳定) |

---

## ⚙️ 系统要求

- Python 3.9+
- OpenClaw (用于 Hook 集成)
- Git
- pip

---

## 📄 License

MIT — 随便用，引用来源即可。

---

Built with 🧠 by [mars82311111](https://github.com/mars82311111/super-mem)
