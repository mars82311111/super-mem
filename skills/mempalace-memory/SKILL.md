# MemPalace Memory Skill (Enhanced)

基于 MemPalace（22k⭐ · Benchmark 最高分） + SM6 精华功能融合的记忆系统。

## 系统架构

```
消息入口
  ↓
[hook] message:preprocessed 自动触发
  ↓
mempalace-recall hook (TypeScript)
  ↓
1. strip_metadata() — 清洗 [user:ou_xxx] 等元数据
  ↓
2. mempalace_cli.py search
  ↓
3. dedup_results() — Levenshtein >85% 重复去重
  ↓
4. mmr_rerank() — 多样性重排
  ↓
5. 注入 bodyForAgent → 模型响应
```

## 核心功能

| 功能 | 来源 | 状态 |
|------|------|------|
| 自动 hook 注入 | SM6 | ✅ hook 已就绪 |
| MMR 多样性重排 | SM6 | ✅ 已实现 |
| Levenshtein 去重 | SM6 | ✅ 已实现 |
| 元数据清洗 | SM6 | ✅ 已实现 |
| ChromaDB forget | SM6 | ✅ 已实现 |
| BM25+向量混合搜索 | MemPalace | ✅ 原有 |
| 4层记忆栈 | MemPalace | ✅ 原有 |
| 对话挖掘 | MemPalace | ✅ 原有 |
| Palace Graph | MemPalace | ✅ 原有 |

## CLI 命令

```bash
# 增强搜索（MMR + 去重 + 清洗）
/usr/bin/python3 ~/.openclaw/workspace/skills/mempalace-memory/scripts/mempalace_cli.py search "查询" --limit 5

# 状态检查
/usr/bin/python3 ~/.openclaw/workspace/skills/mempalace-memory/scripts/mempalace_cli.py status

# 唤醒（启动上下文）
/usr/bin/python3 ~/.openclaw/workspace/skills/mempalace-memory/scripts/mempalace_cli.py wake-up

# 增量挖掘
/usr/bin/python3 ~/.openclaw/workspace/skills/mempalace-memory/scripts/mempalace_cli.py mine

# 删除记忆（ChromaDB）
/usr/bin/python3 ~/.openclaw/workspace/skills/mempalace-memory/scripts/mempalace_cli.py forget <memory_id>
```

## 增强层

- `mempalace_reranker.py` — MMR + 去重 + 元数据清洗
- `mempalace_cli.py` — 增强版 CLI（集成上述功能）
- Hook: `~/.openclaw/hooks/mempalace-recall/`

## 数据

- MemPalace 数据：`~/.mempalace/palace`
- 索引 workspace：99 文件，313 抽屉

## 注意

- hook 已注册在 `message:preprocessed`，全自动触发
- 重要记忆直接调用 `mempalace_cli.py remember` 或存入 MEMORY.md
- 使用 `trash > rm` 保护数据
