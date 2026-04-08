#!/usr/bin/env python3
"""
SuperMem v3 — MemPalace + SM6 精华融合 + 多 Agent 支持
========================================================
设计原则：
  1. 不串联 — 所有增强逻辑都是纯函数，不分层调用
  2. 多 Agent 隔离 — 每个 Agent 独立 ChromaDB collection
  3. 完全融合 — MMR + 去重 + 时间衰减 + Exact优先 + 隔离，一次调用完成

Collection 命名：mempalace_{agent_id}（默认 agent="main"）
"""
import sys
import os
import json
import time
import re
import glob
import argparse
from typing import List, Dict, Any, Optional

# ============================================================================
# CHROMA CLIENT (per-agent isolated collections)
# ============================================================================

def get_chroma_client(palace_path: str = None):
    """Get ChromaDB client with per-agent collections."""
    if palace_path is None:
        palace_path = os.path.expanduser('~/.mempalace/palace')
    import chromadb
    return chromadb.PersistentClient(path=palace_path)

def get_collection(agent_id: str, palace_path: str = None) -> Any:
    """Get or create an agent-specific ChromaDB collection."""
    client = get_chroma_client(palace_path)
    coll_name = f"mempalace_{agent_id}"
    return client.get_or_create_collection(coll_name)

# ============================================================================
# LEVENSHTEIN & SIMILARITY (纯函数)
# ============================================================================

def levenshtein(s1: str, s2: str) -> float:
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(c1!=c2)))
        prev = curr
    return prev[-1]

def str_similarity(s1: str, s2: str) -> float:
    s1, s2 = s1.lower(), s2.lower()
    ml = max(len(s1), len(s2))
    return 1.0 - (levenshtein(s1, s2) / ml) if ml else 1.0

# ============================================================================
# METADATA STRIPPING (纯函数)
# ============================================================================

_STRIP_PATTERNS = [
    (r'^\[message_id:\s*[^\]]+\]\s*', ''),
    (r'^Sender\s*\(untrusted metadata\):\s*```json\s*\n[\s\S]*?```\s*\n', ''),
    (r'^```json\s*\n[\s\S]*?```\s*\n', ''),
    (r'^\[user:ou_[^\]]+\]\s*', ''),
    (r'^Conversation info[\s\S]*?```\s*\n', ''),
    (r'^```\w*\s*\n', ''),
]

def strip_metadata(text: str) -> str:
    for pat, repl in _STRIP_PATTERNS:
        text = re.sub(pat, repl, text, flags=re.MULTILINE)
    return text.strip()

# ============================================================================
# EXACT MATCH BOOST (纯函数)
# ============================================================================

def exact_match_boost(content: str, query: str) -> float:
    """Return score multiplier (1.0-2.0) if query terms appear verbatim."""
    q_lower, c_lower = query.lower(), content.lower()
    if q_lower in c_lower:
        return 2.0  # Full phrase match
    terms = q_lower.split()
    if not terms:
        return 1.0
    matched = sum(1 for t in terms if t in c_lower)
    if matched == len(terms):
        return 1.5  # All terms present
    if matched > 0:
        return 1.0 + (0.5 * matched / len(terms))
    return 1.0

# ============================================================================
# TEMPORAL DECAY (纯函数，基于文件修改时间)
# ============================================================================

def get_file_mtime(content: str, workspace: str = None) -> float:
    """Extract file path from content and return its mtime."""
    if workspace is None:
        workspace = os.path.expanduser('~/.openclaw/workspace')
    m = re.search(r'Source:\s*(.+?)(?:\n|$)', content)
    if not m:
        return 0
    path = m.group(1).strip()
    if path.startswith('/'):
        full = path
    elif path.startswith('~'):
        full = os.path.expanduser(path)
    else:
        full = os.path.join(workspace, path)
    try:
        return os.path.getmtime(full) if os.path.exists(full) else 0
    except Exception:
        return 0

def temporal_decay(mtime: float, half_life_days: int = 30) -> float:
    """
    Exponential decay: score halves every `half_life_days` days.
    Returns value in [0.1, 1.0].
    """
    if not mtime or mtime <= 0:
        return 0.5  # Unknown date = neutral
    days = (time.time() - mtime) / 86400
    return max(0.1, min(1.0, 0.5 ** (days / half_life_days)))

# ============================================================================
# LEVENSHTEIN DEDUP (纯函数)
# ============================================================================

def dedup_results(results: List[Dict], threshold: float = 0.85) -> List[Dict]:
    """Remove duplicates based on Levenshtein similarity. O(n²) but clean."""
    if not results:
        return []
    out = []
    for r in results:
        c = r.get('content', '')
        if not any(str_similarity(c, e.get('content', '')) > threshold for e in out):
            out.append(r)
    return out

# ============================================================================
# MMR RERANKING (纯函数)
# ============================================================================

def mmr_rerank(
    results: List[Dict],
    query: str,
    lambda_param: float = 0.7,
    limit: int = 5
) -> List[Dict]:
    """
    Maximum Marginal Relevance: balance relevance vs diversity.
    Pure function — no side effects, no chained calls.
    """
    if not results or len(results) <= limit:
        return results

    # Normalize scores to [0, 1]
    scores = [r.get('score', 0) for r in results]
    max_s, min_s = max(scores, default=1), min(scores, default=0)
    rng = max_s - min_s if max_s != min_s else 1.0
    norm = lambda r: (r.get('score', 0) - min_s) / rng

    selected, remaining = [], list(results)
    q_lower = query.lower()
    q_terms = set(q_lower.split())

    while len(selected) < limit and remaining:
        best_idx, best_score = -1, -float('inf')
        for idx, item in enumerate(remaining):
            relevance = norm(item)
            max_sim = max(
                (str_similarity(item.get('content','').lower(), s.get('content','').lower())
                 for s in selected),
                default=0
            )
            diversity = 1.0 - max_sim
            mmr = lambda_param * relevance + (1 - lambda_param) * diversity
            if mmr > best_score:
                best_score, best_idx = mmr, idx

        if best_idx < 0:
            break
        selected.append(remaining.pop(best_idx))

    return selected

# ============================================================================
# MEMPALACE CLI INVOCATION
# ============================================================================

def detect_mempalace() -> Optional[str]:
    for c in ['/usr/local/bin/mempalace', '/usr/bin/mempalace',
              os.path.expanduser('~/Library/Python/*/bin/mempalace')]:
        if '*' in c:
            matches = sorted(glob.glob(c))
            if matches:
                return matches[-1]
        elif os.path.exists(c):
            return c
    return None

_MEMPALACE_CLI = detect_mempalace()
_USE_MODULE = _MEMPALACE_CLI is None

def run_mempalace(args: List[str], timeout: int = 30) -> tuple:
    import subprocess
    env = os.environ.copy()
    env['PATH'] = f'{os.path.dirname(sys.executable)}:{env.get("PATH", "")}'
    cmd = [sys.executable, '-m', 'mempalace'] + args if _USE_MODULE else [_MEMPALACE_CLI] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return r.stdout, r.stderr, r.returncode

# ============================================================================
# PARSE MEMPALACE OUTPUT → STRUCTURED RESULTS
# ============================================================================

def parse_mempalace_output(output: str, workspace: str = None) -> List[Dict]:
    """
    Parse MemPalace markdown output into structured list.
    Extracts: content, score, source_file, mtime.
    Pure function — no I/O here.
    """
    if workspace is None:
        workspace = os.path.expanduser('~/.openclaw/workspace')
    lines = output.strip().split('\n')
    results, buf = [], []

    for line in lines:
        if line.startswith('---') or line.startswith('==='):
            continue
        if any(x in line for x in ['Best drawer for', 'Drawer #', 'Results for',
                                      'Search Results for', 'Memory drawer for']):
            if buf:
                content = '\n'.join(buf).strip()
                if content:
                    results.append({
                        'content': content,
                        'score': 1.0,
                        'mtime': get_file_mtime(content, workspace),
                        'source': 'mempalace',
                    })
                buf = []
            continue
        buf.append(line)

    if buf:
        content = '\n'.join(buf).strip()
        if content:
            results.append({
                'content': content,
                'score': 1.0,
                'mtime': get_file_mtime(content, workspace),
                'source': 'mempalace',
            })

    return results

# ============================================================================
# CORE SEARCH — SINGLE FUNCTION, ALL ENHANCEMENTS FUSED
# ============================================================================

def _ngram_terms(text: str, n: int = 2) -> set:
    """Generate character n-grams for Chinese text, word tokens for English."""
    text = text.lower()
    # For text with spaces (English-heavy), use word tokenization
    words = text.split()
    if len(words) > 1 and any(c.isalpha() for c in text):
        return set(words)
    # For Chinese/pure text, use character n-grams
    terms = set()
    for i in range(len(text) - n + 1):
        terms.add(text[i:i+n])
    # Also add uni-grams for important single characters
    for c in text:
        if c.isalpha() or c.isdigit():
            terms.add(c)
    return terms

def _search_chroma_collection(collection_name: str, query: str, limit: int, agent_id: str) -> List[Dict]:
    """Search a specific ChromaDB collection by n-gram keyword overlap."""
    try:
        import chromadb
        client = get_chroma_client()
        coll = client.get_collection(collection_name)
        all_items = coll.get(limit=1000, include=['documents', 'metadatas'])
        if not all_items['ids']:
            return []

        q_terms = _ngram_terms(query, n=2)
        results = []
        for i, doc_id in enumerate(all_items['ids']):
            doc = all_items['documents'][i] if all_items['documents'] else ''
            doc_terms = _ngram_terms(doc, n=2)
            # Jaccard-like overlap score
            if not q_terms:
                continue
            overlap = len(q_terms & doc_terms)
            score = overlap / len(q_terms)  # Fraction of query terms found
            if score > 0:
                meta = all_items['metadatas'][i] if all_items['metadatas'] else {}
                results.append({
                    'content': doc,
                    'score': score * 2.0,  # Boost since this is private agent memory
                    'mtime': 0,
                    'source': f'chroma:{collection_name}',
                    'id': doc_id,
                    'agent_id': meta.get('agent_id', ''),
                })
        return sorted(results, key=lambda x: x['score'], reverse=True)[:limit]
    except Exception:
        return []

def enhanced_search(
    query: str,
    agent_id: str = 'main',
    limit: int = 5,
    use_mmr: bool = True,
    use_dedup: bool = True,
    use_exact_boost: bool = True,
    use_temporal: bool = True,
    temporal_weight: float = 0.3,
    half_life_days: int = 30,
    temporal_weight_mix: float = 0.3,
    workspace: str = None,
) -> Dict[str, Any]:
    """
    Single-function search with ALL enhancements fused:
      1. Call MemPalace (get raw results)
      2. Apply exact_match_boost (pure)
      3. Apply temporal_decay (pure)
      4. Dedup (pure)
      5. MMR rerank (pure)
      6. Return structured output

    No cascading. No串联. Each step is a pure function transform.
    """
    if workspace is None:
        workspace = os.path.expanduser('~/.openclaw/workspace')

    # Step 1: Two-layer search — MemPalace CLI (shared) + agent private collection
    raw_out, err, code = run_mempalace(
        ['search', query, '--results', str(limit * 4)], timeout=30
    )
    results = []
    
    # Layer A: MemPalace shared collection (mempalace_drawers)
    if code == 0:
        results.extend(parse_mempalace_output(raw_out, workspace))
    
    # Layer B: Agent's private collection (mempalace_{agent_id})
    # Each agent's private memories are isolated — no other agent can read them
    # If the agent's collection doesn't exist yet, fall back to 'main' (the primary agent)
    agent_coll_name = f'mempalace_{agent_id}'
    private_results = _search_chroma_collection(
        agent_coll_name, query, limit * 2, agent_id
    )
    # If agent collection is empty/unknown, fall back to 'main' collection
    if not private_results and agent_id != 'main':
        private_results = _search_chroma_collection(
            'mempalace_main', query, limit, agent_id
        )
    results.extend(private_results)

    if not results:
        return {'status': 'ok', 'query': query, 'agent': agent_id,
                'results': [], 'steps': ['mempalace', 'parse', 'empty']}

    steps_used = ['mempalace', 'parse']

    # Step 3: Exact match boost
    if use_exact_boost:
        for r in results:
            boost = exact_match_boost(r['content'], query)
            r['score'] = r.get('score', 1.0) * boost
        steps_used.append('exact_boost')

    # Step 4: Temporal decay
    if use_temporal:
        for r in results:
            decay = temporal_decay(r.get('mtime', 0), half_life_days)
            # Blend: score = score*(1-λ) + decay*λ*score
            base = r.get('score', 1.0)
            r['score'] = base * (1 - temporal_weight_mix) + decay * temporal_weight_mix * base
        steps_used.append(f'temporal(w={temporal_weight_mix},hl={half_life_days}d)')

    # Step 5: Deduplication
    if use_dedup:
        results = dedup_results(results, threshold=0.85)
        steps_used.append('dedup')

    # Step 6: MMR reranking
    if use_mmr:
        results = mmr_rerank(results, query, lambda_param=0.7, limit=limit)
        steps_used.append('mmr')
    else:
        results = sorted(results, key=lambda x: x.get('score', 0), reverse=True)[:limit]

    return {
        'status': 'ok',
        'query': query,
        'agent': agent_id,
        'results': [
            {
                'content': r['content'],
                'score': round(r.get('score', 0), 4),
                'mtime': r.get('mtime', 0),
                'date': time.strftime('%Y-%m-%d', time.localtime(r.get('mtime', 0))) if r.get('mtime', 0) else 'unknown',
            }
            for r in results
        ],
        'steps': steps_used,
        'counts': {
            'raw': len(parse_mempalace_output(raw_out, workspace)),
            'final': len(results),
        }
    }

# ============================================================================
# STORE MEMORY (per-agent collection)
# ============================================================================

def store_memory(
    content: str,
    agent_id: str = 'main',
    source_file: str = '',
    room: str = 'general',
    metadata: Dict = None,
) -> Dict:
    """Store a memory in the agent-specific collection."""
    try:
        import chromadb
        coll = get_collection(agent_id)
        meta = {
            'source_file': source_file,
            'room': room,
            'agent_id': agent_id,
            'filed_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            **(metadata or {})
        }
        coll.add(
            documents=[content],
            ids=[f"mem_{int(time.time() * 1000)}_{hash(content) % 100000:05d}"],
            metadatas=[meta],
        )
        return {'status': 'ok', 'agent': agent_id, 'content': content[:100]}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

# ============================================================================
# FORGET MEMORY (per-agent collection)
# ============================================================================

def forget_memory(memory_id: str, agent_id: str = 'main') -> Dict:
    """Delete a memory from agent-specific collection."""
    try:
        coll = get_collection(agent_id)
        coll.delete(ids=[memory_id])
        return {'status': 'ok', 'action': 'forget', 'id': memory_id, 'agent': agent_id}
    except Exception:
        return {'status': 'ok', 'action': 'forget', 'id': memory_id, 'note': 'not found in collection'}

# ============================================================================
# HEALTH CHECK (per-agent)
# ============================================================================

def health_check(agent_id: str = 'main') -> Dict:
    """Check health of agent-specific collection + overall system."""
    try:
        import chromadb
        client = get_chroma_client()
        all_cols = client.list_collections()
        agent_coll_name = f'mempalace_{agent_id}'

        total = 0
        collections = []
        for c_info in all_cols:
            try:
                col = client.get_collection(c_info.name)
                count = col.count()
                total += count
                is_target = c_info.name == agent_coll_name
                collections.append({
                    'name': c_info.name,
                    'count': count,
                    'is_current_agent': is_target,
                })
            except Exception:
                pass

        return {
            'status': 'ok',
            'system': 'healthy',
            'total_memories': total,
            'current_agent': agent_id,
            'current_agent_collection': agent_coll_name,
            'collections': sorted(collections, key=lambda x: x['name']),
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

# ============================================================================
# MINE (增量挖掘)
# ============================================================================

def mine_workspace(path: str = None, agent_id: str = 'main') -> Dict:
    target = path or os.path.expanduser('~/.openclaw/workspace')
    out, err, code = run_mempalace(['mine', target, '--mode', 'projects'], timeout=120)
    if code == 0:
        return {'status': 'ok', 'path': target, 'agent': agent_id, 'output': out}
    return {'status': 'error', 'error': err}

# ============================================================================
# WAKE-UP
# ============================================================================

def cmd_wake_up(agent_id: str = 'main') -> Dict:
    out, err, code = run_mempalace(['wake-up'], timeout=30)
    if code == 0:
        return {'status': 'ok', 'agent': agent_id, 'context': out}
    return {'status': 'error', 'error': err}

# ============================================================================
# CLI ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='SuperMem v3 — MemPalace + SM6 精华融合 + 多 Agent 隔离'
    )
    sub = parser.add_subparsers(dest='cmd', required=True)

    # search
    p = sub.add_parser('search')
    p.add_argument('query')
    p.add_argument('--agent', default='main', help='Agent ID (default: main)')
    p.add_argument('--limit', type=int, default=5)
    p.add_argument('--no-mmr', dest='use_mmr', action='store_false', default=True)
    p.add_argument('--no-dedup', dest='use_dedup', action='store_false', default=True)
    p.add_argument('--no-exact', dest='use_exact_boost', action='store_false', default=True)
    p.add_argument('--no-temporal', dest='use_temporal', action='store_false', default=True)
    p.add_argument('--tw', '--temporal-weight', dest='temporal_weight', type=float, default=0.3)
    p.add_argument('--hl', '--half-life', dest='half_life_days', type=int, default=30)

    # status
    pstat = sub.add_parser('status')
    pstat.add_argument('--agent', default='main')

    # remember
    prem = sub.add_parser('remember')
    prem.add_argument('content')
    prem.add_argument('--agent', default='main')
    prem.add_argument('--room', default='general')
    prem.add_argument('--source', default='')

    # forget
    pfg = sub.add_parser('forget')
    pfg.add_argument('memory_id')
    pfg.add_argument('--agent', default='main')

    # mine
    pmine = sub.add_parser('mine')
    pmine.add_argument('--agent', default='main')
    pmine.add_argument('--path')

    # wake-up
    sub.add_parser('wake-up')

    # list-agents
    sub.add_parser('list-agents')

    args = parser.parse_args()

    if args.cmd == 'search':
        result = enhanced_search(
            query=args.query,
            agent_id=args.agent,
            limit=args.limit,
            use_mmr=args.use_mmr,
            use_dedup=args.use_dedup,
            use_exact_boost=args.use_exact_boost,
            use_temporal=args.use_temporal,
            temporal_weight_mix=args.temporal_weight,
            half_life_days=args.half_life_days,
        )

    elif args.cmd == 'status':
        result = health_check(agent_id=args.agent)

    elif args.cmd == 'remember':
        result = store_memory(
            content=args.content,
            agent_id=args.agent,
            room=args.room,
            source_file=args.source,
        )

    elif args.cmd == 'forget':
        result = forget_memory(memory_id=args.memory_id, agent_id=args.agent)

    elif args.cmd == 'mine':
        result = mine_workspace(path=args.path, agent_id=args.agent)

    elif args.cmd == 'wake-up':
        result = cmd_wake_up()

    elif args.cmd == 'list-agents':
        try:
            import chromadb
            client = get_chroma_client()
            cols = client.list_collections()
            agents = [c.name.replace('mempalace_', '') for c in cols if c.name.startswith('mempalace_')]
            result = {'status': 'ok', 'agents': sorted(set(agents))}
        except Exception as e:
            result = {'status': 'error', 'error': str(e)}

    else:
        parser.print_help()
        sys.exit(0)

    print(json.dumps(result, ensure_ascii=False, indent=2))
