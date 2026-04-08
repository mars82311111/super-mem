# SuperMem 🧠

> MemPalace + SM6 精华融合 · 多 Agent 记忆系统

**22k⭐ MemPalace** 检索质量 + **SM6** 工程化增强 + **多 Agent 隔离**

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
| **ChromaDB 删除** | SM6 | 可删除过时记忆 |
| **子系统健康检查** | SM6 | ChromaDB 抽屉状态一览 |
| **多 Agent 隔离** | SuperMem | 每个 Agent 独立 ChromaDB Collection |
| **两层记忆搜索** | SuperMem | 共享文件 + 私有记忆 |
| **中文 N-gram** | SuperMem | 中文文本语义匹配（2-gram） |
| **完全本地运行** | MemPalace | 无需 API key |

---

## 🚀 一键安装

```bash
curl -sSL https://raw.githubusercontent.com/mars82311111/super-mem/main/scripts/install.sh | bash
```

---

## 📖 使用方法

### 增强搜索（默认）
```bash
python3 scripts/super_mem_cli.py search "查询内容"

# 指定时间衰减权重（0.0=只看相关性，1.0=只看新旧）
python3 scripts/super_mem_cli.py search "查询" --tw 0.3

# 设置记忆半衰期（天）
python3 scripts/super_mem_cli.py search "查询" --hl 30

# 关闭某些增强
python3 scripts/super_mem_cli.py search "查询" --no-mmr --no-dedup
```

### 多 Agent 搜索
```bash
# 主 Agent（CEO）搜索
python3 scripts/super_mem_cli.py search "查询" --agent main

# 子 Agent 搜索
python3 scripts/super_mem_cli.py search "查询" --agent planner
python3 scripts/super_mem_cli.py search "查询" --agent coder
```

### 存储私人记忆
```bash
# 存储到当前 Agent 的私有 Collection
python3 scripts/super_mem_cli.py remember "记住城总喜欢暗色模式" --agent main --room preferences
```

### 健康检查
```bash
python3 scripts/super_mem_cli.py status --agent main
```

### 删除记忆
```bash
python3 scripts/super_mem_cli.py forget <memory_id> --agent main
```

### 增量挖掘
```bash
python3 scripts/super_mem_cli.py mine --agent main --path /your/workspace
```

### 启动唤醒
```bash
python3 scripts/super_mem_cli.py wake-up
```

### 列出所有 Agent
```bash
python3 scripts/super_mem_cli.py list-agents
```

---

## 🏗️ 多 Agent 架构

```
┌─────────────────────────────────────────────────────────┐
│                    SuperMem Memory                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────┐     ┌──────────────────────────┐  │
│  │  mempalace_drawers │     │   Per-Agent Collections   │  │
│  │  (共享·文件挖掘)    │     │                          │  │
│  │                    │     │  ┌─ mempalace_main ──┐  │  │
│  │  从 workspace     │     │  │  CEO 私有记忆       │  │  │
│  │  文件自动挖掘     │     │  └───────────────────┘  │  │
│  │                    │     │  ┌─ mempalace_planner┐  │  │
│  │  所有 Agent 共享   │     │  │  Planner 私有记忆   │  │  │
│  │  不可删除          │     │  └───────────────────┘  │  │
│  └──────────────────┘     │  ┌─ mempalace_coder ──┐  │  │
│                            │  │  Coder 私有记忆    │  │  │
│                            │  └───────────────────┘  │  │
│                            └──────────────────────────┘  │
│                                                          │
│  搜索流程：                                              │
│  1. 搜 mempalace_drawers（共享）                        │
│  2. 搜 mempalace_{agent}（私有）                        │
│  3. Exact Match Boost                                   │
│  4. Temporal Decay                                      │
│  5. Levenshtein 去重                                    │
│  6. MMR 多样性重排                                       │
└─────────────────────────────────────────────────────────┘
```

### 隔离保证

- **主 Agent（main）**：可读写 `mempalace_drawers`（共享）+ `mempalace_main`（私有）
- **子 Agent（planner/coder）**：可读写 `mempalace_drawers`（共享）+ `mempalace_{agent}`（私有）
- **私有 Collection 不交叉**：planner 无法读取 main 的私有记忆
- **共享文件统一挖掘**：`mempalace_drawers` 由 workspace 自动维护，所有 Agent 共享

---

## 🔧 设计原则

### 不串联（No Cascading）

所有增强逻辑均为**纯函数**，按序执行、无状态共享：

```
mempalace search → exact_match_boost() → temporal_decay() → dedup() → mmr()
     ↓                    ↓                   ↓              ↓         ↓
  原始结果           纯函数transform      纯函数transform  纯函数transform 纯函数transform
```

每一步都是独立的 transform，不依赖上一步的副作用。

### 完全融合

- 不拆分服务、不创建进程链
- 单文件 CLI、一个 Hook、一个 Collection
- 故障率低、易调试、易维护

---

## ⚙️ 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--agent` | Agent ID，决定搜索哪个私有 Collection | `main` |
| `--tw` | 时间衰减权重（0.0-1.0） | `0.3` |
| `--hl` | 记忆半衰期（天） | `30` |
| `--limit` | 返回结果数 | `5` |
| `--no-mmr` | 禁用 MMR 多样性重排 | False |
| `--no-dedup` | 禁用 Levenshtein 去重 | False |
| `--no-exact` | 禁用 Exact Match 优先 | False |
| `--no-temporal` | 禁用时间衰减 | False |

---

## ⚙️ 系统要求

- Python 3.9+
- OpenClaw（用于 Hook 集成）
- Git、pip

---

## 📄 License

MIT

---

Built with 🧠 by [mars82311111](https://github.com/mars82311111/super-mem)
