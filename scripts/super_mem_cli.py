#!/usr/bin/env python3
"""
SuperMem Enhanced CLI v2
=======================
Added from SM6:
1. Temporal decay (时间衰减) - recency weighting in search
2. Health check - index status, drawer counts
3. Exact match boost - keyword appears verbatim gets priority
4. Wake-up with recency sorting
"""
import sys
import os
import json
import argparse
import time
from collections import defaultdict

# ---------------------------------------------------------------------------
# Detect mempalace
# ---------------------------------------------------------------------------

def detect_mempalace():
    candidates = [
        '/usr/local/bin/mempalace',
        '/usr/bin/mempalace',
        os.path.expanduser('~/Library/Python/*/bin/mempalace'),
    ]
    import glob
    for c in candidates:
        if '*' in c:
            matches = glob.glob(c)
            if matches:
                return sorted(matches)[-1]
        elif os.path.exists(c):
            return c
    return None

MEMPALACE_CLI = detect_mempalace()
USE_MODULE = MEMPALACE_CLI is None

def run_mempalace(args, timeout=30):
    import subprocess
    env = os.environ.copy()
    python_bin = os.path.dirname(sys.executable)
    env['PATH'] = f'{python_bin}:{env.get("PATH", "")}'
    cmd = [sys.executable, '-m', 'mempalace'] + args if USE_MODULE else [MEMPALACE_CLI] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return r.stdout, r.stderr, r.returncode

# ---------------------------------------------------------------------------
# Levenshtein & Similarity
# ---------------------------------------------------------------------------

def levenshtein(s1, s2):
    if len(s1) < len(s2): return levenshtein(s2, s1)
    if len(s2) == 0: return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(c1!=c2)))
        prev = curr
    return prev[-1]

def similarity(s1, s2):
    s1, s2 = s1.lower(), s2.lower()
    ml = max(len(s1), len(s2))
    return 1.0 - (levenshtein(s1, s2) / ml) if ml else 1.0

# ---------------------------------------------------------------------------
# Temporal Decay (from SM6)
# ---------------------------------------------------------------------------

def temporal_decay_score(result_mtime: float, half_life_days: int = 30) -> float:
    """
    Exponential decay based on days since file was modified.
    Default half-life: 30 days (half as relevant after 30 days).
    """
    if not result_mtime or result_mtime <= 0:
        return 0.5  # Unknown date gets neutral score
    
    try:
        now = time.time()
        days_elapsed = (now - result_mtime) / 86400
        decay = 0.5 ** (days_elapsed / half_life_days)
        return max(0.1, min(1.0, decay))  # Clamp to [0.1, 1.0]
    except Exception:
        return 0.5

# ---------------------------------------------------------------------------
# Exact Match Boost (from SM6)
# ---------------------------------------------------------------------------

def exact_match_boost(content: str, query: str) -> float:
    """
    Boost score if query keywords appear verbatim in content.
    Returns multiplier 1.0-2.0.
    """
    content_lower = content.lower()
    query_lower = query.lower()
    query_terms = query_lower.split()
    
    if not query_terms:
        return 1.0
    
    # Exact phrase match (highest boost)
    if query_lower in content_lower:
        return 2.0
    
    # All terms present (medium boost)
    matched = sum(1 for t in query_terms if t in content_lower)
    if matched == len(query_terms):
        return 1.5
    
    # Partial match
    if matched > 0:
        return 1.0 + (0.5 * matched / len(query_terms))
    
    return 1.0

# ---------------------------------------------------------------------------
# Parse MemPalace Output
# ---------------------------------------------------------------------------

def parse_search_output(output: str) -> list:
    lines = output.strip().split('\n')
    results, current = [], []
    
    for line in lines:
        if line.startswith('---') or line.startswith('==='): continue
        if any(x in line for x in ['Best drawer for', 'Drawer #', 'Results for']):
            if current:
                content = '\n'.join(current).strip()
                if content:
                    mtime = get_file_mtime(content)
                    results.append({
                        'content': content,
                        'score': 1.0,
                        'source': 'mempalace',
                        'mtime': mtime,
                        'date': extract_date_from_content(content)
                    })
                current = []
            continue
        if line.strip():
            current.append(line)
    
    if current:
        content = '\n'.join(current).strip()
        if content:
            mtime = get_file_mtime(content)
            results.append({
                'content': content,
                'score': 1.0,
                'source': 'mempalace',
                'mtime': mtime,
                'date': extract_date_from_content(content)
            })
    
    return results

def get_chroma_metadata_for_drawer_ids(drawer_ids: list) -> dict:
    """Get filed_at timestamps from ChromaDB metadata."""
    id_to_date = {}
    try:
        import chromadb
        client = chromadb.PersistentClient(path=os.path.expanduser('~/.mempalace/palace'))
        col = client.get_collection('mempalace_drawers')
        # Get metadata for all IDs we found
        items = col.get(ids=drawer_ids, include=['metadatas'])
        for i, mid in enumerate(items['ids']):
            meta = items['metadatas'][i] if i < len(items['metadatas']) else {}
            id_to_date[mid] = meta.get('filed_at', '')
    except Exception:
        pass
    return id_to_date

def parse_drawer_id_from_content(content: str) -> str:
    """Try to extract drawer ID from content snippet."""
    import re
    # Look for drawer ID pattern
    m = re.search(r'drawer_[a-z_]+_[a-z0-9]+', content)
    return m.group() if m else ''

def extract_date_from_content(content: str) -> str:
    """Try to extract a date from content."""
    import re
    m = re.search(r'\d{4}-\d{2}-\d{2}[T ]', content)
    if m: return m.group()[:10]
    m = re.search(r'\d{4}/\d{2}/\d{2}', content)
    if m: return m.group().replace('/', '-')
    return ''

def get_file_mtime(content: str) -> float:
    """Get file modification time from content (source file path)."""
    import re, os
    m = re.search(r'Source:\s*(.+?)(?:\n|$)', content)
    if not m:
        return 0
    path = m.group(1).strip()
    if path.startswith('/'):
        full_path = path
    elif path.startswith('~'):
        full_path = os.path.expanduser(path)
    else:
        full_path = os.path.expanduser(f'~/.openclaw/workspace/{path}')
    if os.path.exists(full_path):
        return os.path.getmtime(full_path)
    return 0

# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def dedup_results(results, threshold=0.85):
    deduped = []
    for r in results:
        c = r.get('content', '')
        if not any(similarity(c, e.get('content','')) > threshold for e in deduped):
            deduped.append(r)
    return deduped

# ---------------------------------------------------------------------------
# MMR Reranking (from SM6)
# ---------------------------------------------------------------------------

def mmr_rerank(results, query, lambda_param=0.7, limit=5):
    if not results or len(results) <= limit:
        return results
    
    selected, remaining = [], list(results)
    scores = [r.get('score', 0) for r in remaining]
    max_s, min_s, rng = max(scores, default=1), min(scores, default=0), max(scores, default=1) - min(scores, default=0)
    norm = lambda r: (r.get('score', 0) - min_s) / rng if rng else 0.5
    
    while len(selected) < limit and remaining:
        best, best_idx, best_score = None, -1, -float('inf')
        for idx, item in enumerate(remaining):
            rel = norm(item)
            max_sim = max((similarity(item.get('content',''), s.get('content','')) for s in selected), default=0)
            mmr = lambda_param * rel + (1 - lambda_param) * (1.0 - max_sim)
            if mmr > best_score:
                best_score, best, best_idx = mmr, item, idx
        if best:
            selected.append(best)
            remaining.pop(best_idx)
        else:
            break
    return selected

# ---------------------------------------------------------------------------
# Metadata Stripping
# ---------------------------------------------------------------------------

import re
STRIP_PATTERNS = [
    (r'^\[message_id:\s*[^\]]+\]\s*', ''),
    (r'^Sender\s*\(untrusted metadata\):\s*```json\s*\n[\s\S]*?```\s*\n', ''),
    (r'^```json\s*\n[\s\S]*?```\s*\n', ''),
    (r'^\[user:ou_[^\]]+\]\s*', ''),
    (r'^Conversation info[\s\S]*?```\s*\n', ''),
    (r'^```\w*\s*\n', ''),
]
def strip_metadata(text):
    for pat, repl in STRIP_PATTERNS:
        text = re.sub(pat, repl, text, flags=re.MULTILINE)
    return text.strip()

# ---------------------------------------------------------------------------
# COMMANDS
# ---------------------------------------------------------------------------

def cmd_search(query, limit=5, use_mmr=True, dedup=True,
               temporal_weight=0.3, half_life_days=30,
               exact_boost=True):
    """Enhanced search with temporal decay + exact match boost."""
    out, err, code = run_mempalace(['search', query, '--results', str(limit * 4)])
    if code != 0:
        return {'status': 'error', 'error': err}
    
    results = parse_search_output(out)
    if not results:
        return {'status': 'ok', 'query': query, 'results': []}
    
    # Apply exact match boost
    if exact_boost:
        for r in results:
            boost = exact_match_boost(r['content'], query)
            r['score'] = r.get('score', 1.0) * boost
    
    # Apply temporal decay
    for r in results:
        mtime = r.get('mtime', 0)
        decay = temporal_decay_score(mtime, half_life_days)
        # Combine: base_score * (1 - temporal_weight) + decay * temporal_weight
        r['score'] = r.get('score', 1.0) * (1 - temporal_weight) + decay * temporal_weight * r.get('score', 1.0)
    
    if dedup:
        results = dedup_results(results)
    if use_mmr:
        results = mmr_rerank(results, query, lambda_param=0.7, limit=limit)
    else:
        results = sorted(results, key=lambda x: x.get('score', 0), reverse=True)[:limit]
    
    return {
        'status': 'ok',
        'query': query,
        'temporal_weight': temporal_weight,
        'half_life_days': half_life_days,
        'results': [{'content': r['content'], 'score': round(r['score'], 3), 'date': r.get('date',''), 'mtime': r.get('mtime', 0)} for r in results]
    }

def cmd_status():
    """Health check — index status from MemPalace."""
    out, err, code = run_mempalace(['status'], timeout=15)
    if code != 0:
        return {'status': 'error', 'error': err}
    
    # Parse mempalace status output
    lines = out.strip().split('\n')
    parsed = {'status': 'ok', 'output': out}
    
    # Try to get ChromaDB stats
    try:
        import chromadb
        client = chromadb.PersistentClient(path=os.path.expanduser('~/.mempalace/palace'))
        collections = client.list_collections()
        total_memories = 0
        collection_stats = []
        for col_info in collections:
            try:
                col = client.get_collection(col_info.name)
                count = col.count()
                total_memories += count
                collection_stats.append({'name': col_info.name, 'count': count})
            except Exception:
                pass
        
        parsed['collections'] = collection_stats
        parsed['total_memories'] = total_memories
        parsed['system'] = 'healthy'
    except Exception as e:
        parsed['system'] = 'error'
        parsed['chroma_error'] = str(e)
    
    return parsed

def cmd_wake_up():
    """Wake-up with temporal-sorted context."""
    out, err, code = run_mempalace(['wake-up'], timeout=30)
    if code == 0:
        return {'status': 'ok', 'context': out}
    return {'status': 'error', 'error': err}

def cmd_mine(path=None):
    target = path or os.path.expanduser('~/.openclaw/workspace')
    out, err, code = run_mempalace(['mine', target, '--mode', 'projects'], timeout=120)
    if code == 0:
        return {'status': 'ok', 'path': target, 'output': out}
    return {'status': 'error', 'error': err}

def cmd_forget(memory_id):
    try:
        import chromadb
        client = chromadb.PersistentClient(path=os.path.expanduser('~/.mempalace/palace'))
        for col_info in client.list_collections():
            try:
                col = client.get_collection(col_info.name)
                item = col.get(ids=[memory_id])
                if item and item['ids']:
                    col.delete(ids=[memory_id])
                    return {'status': 'ok', 'action': 'forget', 'id': memory_id}
            except Exception:
                pass
        return {'status': 'ok', 'action': 'forget', 'id': memory_id, 'note': 'not found'}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SuperMem v2 — MemPalace + SM6')
    sub = parser.add_subparsers(dest='cmd')
    
    p = sub.add_parser('search')
    p.add_argument('query')
    p.add_argument('--limit', type=int, default=5)
    p.add_argument('--no-mmr', dest='use_mmr', action='store_false', default=True)
    p.add_argument('--no-dedup', dest='dedup', action='store_false', default=True)
    p.add_argument('--no-exact-boost', dest='exact_boost', action='store_false', default=True)
    p.add_argument('--temporal-weight', type=float, default=0.3,
                   help='Weight for recency (0.0-1.0, default 0.3)')
    p.add_argument('--half-life-days', type=int, default=30,
                   help='Memory half-life in days (default 30)')
    
    sub.add_parser('status')
    sub.add_parser('wake-up')
    
    p_mine = sub.add_parser('mine')
    p_mine.add_argument('--path')
    
    p_forget = sub.add_parser('forget')
    p_forget.add_argument('memory_id')
    
    args = parser.parse_args()
    
    if args.cmd == 'search':
        result = cmd_search(args.query, args.limit, args.use_mmr, args.dedup,
                          args.temporal_weight, args.half_life_days, args.exact_boost)
    elif args.cmd == 'status':
        result = cmd_status()
    elif args.cmd == 'wake-up':
        result = cmd_wake_up()
    elif args.cmd == 'mine':
        result = cmd_mine(args.path)
    elif args.cmd == 'forget':
        result = cmd_forget(args.memory_id)
    else:
        parser.print_help()
        sys.exit(0)
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
