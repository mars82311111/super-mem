#!/usr/bin/env python3
"""
SuperMem v4.1 — 根因修复完整版
================================================
修复清单：
1. Layer A mtime：shared content 用 metadata.filed_at，不再依赖"Source:"注释
2. Bridge 去重：删除旧格式(mp_xxx)，幂等同步(mp_bridge_xxx)
3. remember 返回 memory_id
4. 混合搜索：向量 + 关键词双保险，覆盖短中文查询全部场景
5. 关键词匹配：中文 2-gram + 英文词根，适合 nomic-embed-text 盲区
"""
import sys, os, json, time, re, glob, argparse, subprocess
from typing import List, Dict, Any

# ============================================================================
# 1. OLLAMA EMBEDDING
# ============================================================================
_OLLAMA = "http://localhost:11434/api/embeddings"
_EMBED_MODEL = "nomic-embed-text"

def ollama_embed(texts: List[str]) -> List[List[float]]:
    vecs = []
    for text in texts:
        payload = {"model": _EMBED_MODEL, "prompt": text}
        try:
            r = subprocess.run(
                ["curl", "-s", "-X", "POST", _OLLAMA,
                 "-H", "Content-Type: application/json", "-d", json.dumps(payload)],
                capture_output=True, text=True, timeout=30
            )
            d = json.loads(r.stdout)
            v = d.get("embedding", None)
            if not v or len(v) == 0:
                v = [0.0] * 768
            vecs.append(v)
        except Exception:
            vecs.append([0.0] * 768)
    return vecs

# ============================================================================
# 2. CHROMADB
# ============================================================================
def _get_client():
    import chromadb
    return chromadb.PersistentClient(path=os.path.expanduser("~/.super-mem/chroma"))

def _get_coll(name: str):
    return _get_client().get_or_create_collection(name, metadata={"shared": "true"})

# ============================================================================
# 3. PURE FUNCTIONS
# ============================================================================
def cosine_sim(a, b) -> float:
    import numpy as np
    a = np.array(a, dtype=np.float64)
    b = np.array(b, dtype=np.float64)
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (na * nb))

def levenshtein(s1: str, s2: str) -> float:
    if len(s1) < len(s2): return levenshtein(s2, s1)
    if len(s2) == 0: return len(s1)
    p = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        c = [i + 1]
        for j, c2 in enumerate(s2):
            c.append(min(p[j+1]+1, c[j]+1, p[j]+(c1!=c2)))
        p = c
    return float(p[-1])

def str_sim(s1: str, s2: str) -> float:
    s1, s2 = s1.lower(), s2.lower()
    ml = max(len(s1), len(s2))
    return 1.0 - levenshtein(s1, s2) / ml if ml else 1.0

def tokenize_chinese(text: str) -> set:
    """中文2-gram分词 + 英文词根提取。"""
    tokens = set()
    # 中文2-gram
    for i in range(len(text) - 1):
        c1, c2 = text[i], text[i+1]
        if '\u4e00' <= c1 <= '\u9fff' and '\u4e00' <= c2 <= '\u9fff':
            tokens.add(text[i:i+2])
    # 英文词（长度>=2）
    for w in re.findall(r'[a-zA-Z0-9]{2,}', text):
        tokens.add(w.lower())
        # 子串（3-gram for English）
        if len(w) >= 3:
            for j in range(len(w) - 2):
                tokens.add(w[j:j+3].lower())
    return tokens

def keyword_score(query: str, content: str) -> float:
    """
    关键词得分：查询与内容的关键词重叠度。
    同时用原始词和n-gram，适合短查询。
    """
    q_lower = query.lower()
    c_lower = content.lower()
    # 完整查询命中
    if q_lower in c_lower:
        return 2.0
    # 关键词tokenize
    q_tokens = tokenize_chinese(query)
    c_tokens = tokenize_chinese(content)
    if not q_tokens:
        return 1.0
    overlap = sum(1 for t in q_tokens if t in c_tokens)
    return 1.0 + overlap / len(q_tokens)

def exact_boost(content: str, query: str) -> float:
    q, c = query.lower(), content.lower()
    if q in c: return 2.0
    terms = [t for t in query.split() if len(t) >= 2]
    if not terms: return 1.0
    m = sum(1 for t in terms if t in c)
    if m == len(terms): return 1.5
    return 1.0 + 0.5 * m / len(terms) if m else 1.0

def temporal_decay(mtime: float, half_life: int = 30) -> float:
    if not mtime or mtime <= 0: return 0.5
    days = (time.time() - mtime) / 86400
    return max(0.1, min(1.0, 0.5 ** (days / half_life)))

def parse_filed_at(filed_at_str) -> float:
    if not filed_at_str: return 0.0
    try:
        if isinstance(filed_at_str, (int, float)):
            return float(filed_at_str)
        t = filed_at_str.replace('T', ' ').replace('Z', '')
        return time.mktime(time.strptime(t[:19], "%Y-%m-%d %H:%M:%S"))
    except: return 0.0

def get_mtime(content: str) -> float:
    m = re.search(r"Source:\s*(.+?)(?:\n|$)", content)
    if not m: return 0
    path = m.group(1).strip()
    if path.startswith("/"): full = path
    elif path.startswith("~"): full = os.path.expanduser(path)
    else: full = os.path.expanduser(f"~/.openclaw/workspace/{path}")
    try: return os.path.getmtime(full) if os.path.exists(full) else 0
    except: return 0

STRIP_PATTERNS = [
    (r'^\[message_id:\s*[^\]]+\]\s*', ""),
    (r'^Sender\s*\(untrusted metadata\):\s*```json\s*\n[\s\S]*?```\s*\n', ""),
    (r'^```json\s*\n[\s\S]*?```\s*\n', ""),
    (r'^\[user:ou_[^\]]+\]\s*', ""),
    (r'^Conversation info[\s\S]*?```\s*\n', ""),
    (r'^```\w*\s*\n', ""),
]
def strip(text: str) -> str:
    for pat, repl in STRIP_PATTERNS:
        text = re.sub(pat, repl, text, flags=re.MULTILINE)
    return text.strip()

def dedup_results(results: List[Dict], thresh: float = 0.85) -> List[Dict]:
    out = []
    for r in results:
        c = r["content"]
        if not any(str_sim(c, e["content"]) > thresh for e in out):
            out.append(r)
    return out

def mmr_rerank(results: List[Dict], query: str, lam: float = 0.7, limit: int = 5) -> List[Dict]:
    if not results or len(results) <= limit: return results
    scores = [r.get("score", 0) for r in results]
    mx, mn = max(scores, default=1), min(scores, default=0)
    rng = mx - mn if mx != mn else 1
    norm = lambda r: (r.get("score", 0) - mn) / rng
    sel, rem = [], list(results)
    while len(sel) < limit and rem:
        best_i, best_s = -1, -float("inf")
        for i, item in enumerate(rem):
            rel = norm(item)
            mx_s = max((str_sim(item["content"].lower(), s["content"].lower()) for s in sel), default=0)
            scr = lam * rel + (1 - lam) * (1 - mx_s)
            if scr > best_s: best_s, best_i = scr, i
        if best_i < 0: break
        sel.append(rem.pop(best_i))
    return sel

# ============================================================================
# 4. BRIDGE — 幂等同步 MemPalace → SuperMem
# ============================================================================
def bridge() -> Dict:
    """
    幂等设计：
    1. 删除旧格式 ID（mp_xxx 但非 mp_bridge_xxx）
    2. 用新格式重新插入（mp_bridge_xxx）
    """
    try:
        import chromadb
        mp = chromadb.PersistentClient(path=os.path.expanduser("~/.mempalace/palace"))
        mp_col = mp.get_collection("mempalace_drawers")
        items = mp_col.get(limit=10000, include=["documents", "metadatas"])
        if not items["ids"]:
            return {"synced": 0, "note": "MemPalace empty"}

        shared = _get_coll("super_mem_shared")

        # 删除旧格式
        all_ids = shared.get(limit=10000, include=[])["ids"]
        old_ids = [mid for mid in all_ids if mid.startswith("mp_") and not mid.startswith("mp_bridge_")]
        if old_ids:
            shared.delete(ids=old_ids)

        # 重新插入（幂等）
        docs, metas, ids, embs = [], [], [], []
        for i, did in enumerate(items["ids"]):
            doc = items["documents"][i] if items["documents"] else ""
            meta = items["metadatas"][i] if items["metadatas"] else {}
            docs.append(doc)
            metas.append({**meta, "source": "mempalace_bridge", "original_id": did})
            ids.append(f"mp_bridge_{did}")
        embs = ollama_embed(docs)
        shared.add(documents=docs, metadatas=metas, ids=ids, embeddings=embs)
        return {"synced": len(docs), "deleted_old": len(old_ids)}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"error": str(e)}

# ============================================================================
# 5. CORE SEARCH (混合向量+关键词)
# ============================================================================
def search(
    query: str,
    agent: str = "main",
    limit: int = 5,
    use_mmr: bool = True,
    use_dedup: bool = True,
    use_exact: bool = True,
    use_temporal: bool = True,
    tw: float = 0.3,
    hl: int = 30,
    kw_weight: float = 0.4,
) -> Dict[str, Any]:
    """
    混合搜索：向量 cosine similarity + 关键词重叠度双保险。
    kw_weight: 关键词权重（0-1），默认 0.4
    """
    clean = strip(query)
    q_emb = ollama_embed([clean])[0]

    shared = _get_coll("super_mem_shared")
    agent_coll = _get_coll(f"super_mem_{agent}")
    all_raw: List[Dict] = []

    # Layer A: shared
    try:
        res = shared.query(
            query_embeddings=[q_emb],
            n_results=limit * 4,
            include=["documents", "metadatas", "embeddings"]
        )
        raw_embs = res.get("embeddings")
        raw_docs = res.get("documents")
        raw_metas = res.get("metadatas")
        layer_embs = raw_embs[0] if raw_embs else []
        docs = raw_docs[0] if raw_docs else []
        metas = raw_metas[0] if raw_metas else []
        for i, doc in enumerate(docs):
            emb = layer_embs[i] if i < len(layer_embs) else None
            vec_score = cosine_sim(q_emb, emb) if emb is not None else 0.0
            meta = metas[i] if i < len(metas) else {}
            # 根因修复：用 metadata.filed_at（解决 shared content 无"Source:"注释的问题）
            filed_at = meta.get("filed_at", 0)
            mtime = parse_filed_at(filed_at) if filed_at else get_mtime(doc)
            all_raw.append({
                "content": doc,
                "vec_score": vec_score,
                "kw_score": keyword_score(clean, doc),
                "score": vec_score,
                "mtime": mtime,
                "source": "shared",
                "meta": meta,
            })
    except Exception:
        pass

    # Layer B: agent private
    try:
        res = agent_coll.query(
            query_embeddings=[q_emb],
            n_results=limit * 2,
            include=["documents", "metadatas", "embeddings"]
        )
        raw_embs = res.get("embeddings")
        raw_docs = res.get("documents")
        raw_metas = res.get("metadatas")
        layer_embs = raw_embs[0] if raw_embs else []
        docs = raw_docs[0] if raw_docs else []
        metas = raw_metas[0] if raw_metas else []
        for i, doc in enumerate(docs):
            emb = layer_embs[i] if i < len(layer_embs) else None
            vec_score = cosine_sim(q_emb, emb) * 1.2 if emb is not None else 0.0
            meta = metas[i] if i < len(metas) else {}
            filed_at = meta.get("filed_at", 0)
            mtime = float(filed_at) if filed_at else time.time()
            all_raw.append({
                "content": doc,
                "vec_score": vec_score,
                "kw_score": keyword_score(clean, doc),
                "score": vec_score,
                "mtime": mtime,
                "source": f"agent:{agent}",
                "meta": meta,
            })
    except Exception:
        pass

    if not all_raw:
        return {
            "status": "ok", "query": query, "agent": agent,
            "results": [], "steps": ["ollama", "empty"]
        }

    # ===== 混合评分：向量 × (1 - kw_weight) + 关键词归一化 × kw_weight =====
    max_vec = max(r["vec_score"] for r in all_raw) if all_raw else 1.0
    for r in all_raw:
        kw_norm = r["kw_score"] / 2.0  # kw_score 范围 1-2，归一化到 0-1
        vec_norm = r["vec_score"] / max_vec if max_vec else 0
        r["score"] = vec_norm * (1 - kw_weight) + kw_norm * kw_weight
        r["score"] *= r["vec_score"]  # 保留绝对量级
    steps = ["ollama", "chroma_query", f"hybrid(kw={kw_weight})"]

    if use_exact:
        for r in all_raw:
            r["score"] *= exact_boost(r["content"], clean)
        steps.append("exact_boost")

    if use_temporal:
        for r in all_raw:
            decay = temporal_decay(r.get("mtime", 0), hl)
            r["score"] = r["score"] * (1 - tw) + r["score"] * decay * tw
        steps.append(f"temporal(w={tw},hl={hl}d)")

    if use_dedup:
        all_raw = dedup_results(all_raw)
        steps.append("dedup")

    if use_mmr:
        all_raw = mmr_rerank(all_raw, clean, lam=0.7, limit=limit)
        steps.append("mmr")
    else:
        all_raw = sorted(all_raw, key=lambda x: x.get("score", 0), reverse=True)[:limit]

    return {
        "status": "ok",
        "query": query,
        "agent": agent,
        "steps": steps,
        "results": [
            {
                "content": r["content"],
                "score": round(r["score"], 4),
                "vec_score": round(r.get("vec_score", 0), 4),
                "kw_score": round(r.get("kw_score", 0), 2),
                "mtime": r.get("mtime", 0),
                "date": time.strftime("%Y-%m-%d", time.localtime(r.get("mtime", 0))) if r.get("mtime", 0) else "unknown",
                "source": r["source"],
            }
            for r in all_raw
        ]
    }

# ============================================================================
# 6. CRUD + STATUS
# ============================================================================
def store(content: str, agent: str = "main", room: str = "general", source: str = "") -> Dict:
    try:
        coll = _get_coll(f"super_mem_{agent}")
        mtime = time.time()
        meta = {"agent_id": agent, "room": room, "source_file": source,
                "filed_at": mtime, "stored_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        doc_id = f"mem_{int(mtime * 1000)}_{abs(hash(content)) % 100000:05d}"
        emb = ollama_embed([content])[0]
        coll.add(documents=[content], metadatas=[meta], ids=[doc_id], embeddings=[emb])
        return {"status": "ok", "agent": agent, "memory_id": doc_id, "content": content[:80]}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def forget(mem_id: str, agent: str = "main") -> Dict:
    deleted = []
    for name in [f"super_mem_{agent}", "super_mem_shared"]:
        try:
            _get_coll(name).delete(ids=[mem_id])
            deleted.append(name)
        except: pass
    return {"status": "ok", "action": "forget", "id": mem_id, "agent": agent,
            "deleted_from": deleted if deleted else ["not_found"]}

def status(agent: str = "main") -> Dict:
    try:
        client = _get_client()
        cols = client.list_collections()
        total = 0; info = []
        for c in cols:
            try:
                col = client.get_collection(c.name)
                cnt = col.count(); total += cnt
                info.append({"name": c.name, "count": cnt})
            except: pass
        return {"status": "ok", "system": "healthy", "total": total,
                "collections": sorted(info, key=lambda x: x["name"])}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def mine(path: str = None) -> Dict:
    target = path or os.path.expanduser("~/.openclaw/workspace")
    try:
        subprocess.run(
            [sys.executable, "-m", "mempalace", "mine", target, "--mode", "projects"],
            capture_output=True, timeout=120
        )
        sync = bridge()
        return {"status": "ok", "path": target, "synced": sync}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def list_agents() -> Dict:
    try:
        client = _get_client()
        cols = client.list_collections()
        agents = sorted({
            c.name.replace("super_mem_", "")
            for c in cols if c.name.startswith("super_mem_") and c.name != "super_mem_shared"
        })
        return {"status": "ok", "agents": agents}
    except Exception as e:
        return {"status": "error", "error": str(e)}

# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SuperMem v4.1")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search")
    sp.add_argument("query")
    sp.add_argument("--agent", "-a", default="main")
    sp.add_argument("--limit", "-n", type=int, default=5)
    sp.add_argument("--no-mmr", dest="mmr", action="store_false", default=True)
    sp.add_argument("--no-dedup", dest="dedup", action="store_false", default=True)
    sp.add_argument("--no-exact", dest="exact", action="store_false", default=True)
    sp.add_argument("--no-temporal", dest="temporal", action="store_false", default=True)
    sp.add_argument("--tw", type=float, default=0.3)
    sp.add_argument("--hl", type=int, default=30)

    sub.add_parser("status")

    sp3 = sub.add_parser("remember")
    sp3.add_argument("content")
    sp3.add_argument("--agent", "-a", default="main")
    sp3.add_argument("--room", "-r", default="general")
    sp3.add_argument("--source", "-s", default="")

    sp4 = sub.add_parser("forget")
    sp4.add_argument("memory_id")
    sp4.add_argument("--agent", "-a", default="main")

    sp5 = sub.add_parser("mine")
    sp5.add_argument("--path")

    sub.add_parser("wake-up")
    sub.add_parser("list-agents")
    sub.add_parser("bridge")

    args = p.parse_args()
    cmd = args.cmd

    if cmd == "search":
        r = search(args.query, agent=args.agent, limit=args.limit,
                   use_mmr=args.mmr, use_dedup=args.dedup, use_exact=args.exact,
                   use_temporal=args.temporal, tw=args.tw, hl=args.hl)
    elif cmd == "status":
        r = status()
    elif cmd == "remember":
        r = store(args.content, agent=args.agent, room=args.room, source=args.source)
    elif cmd == "forget":
        r = forget(args.memory_id, agent=args.agent)
    elif cmd == "mine":
        r = mine(args.path)
    elif cmd == "wake-up":
        r = search(".", agent="main", limit=10)
    elif cmd == "list-agents":
        r = list_agents()
    elif cmd == "bridge":
        r = bridge()
    else:
        p.print_help()
        sys.exit(0)

    print(json.dumps(r, ensure_ascii=False, indent=2))
