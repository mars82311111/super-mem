#!/usr/bin/env python3
"""
SuperMem CLI — MemPalace + SM6 精华融合
====================================
Features:
- MMR diversity reranking
- Levenshtein content deduplication  
- Metadata stripping
- ChromaDB delete (forget)
- Wake-up with context injection
- Auto hook integration

Usage:
    python3 super_mem_cli.py search <query> [--limit 5]
    python3 super_mem_cli.py status
    python3 super_mem_cli.py wake-up
    python3 super_mem_cli.py mine [--path <path>]
    python3 super_mem_cli.py forget <memory_id>
"""
import sys
import os
import json
import argparse

MEMPALACE_CLI = None  # Auto-detected below

def detect_mempalace():
    """Find mempalace CLI in common locations."""
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
    # Fallback: use python -m mempalace
    return None

MEMPALACE_CLI = detect_mempalace()
MEMPALACE_USE_MODULE = MEMPALACE_CLI is None

def run_mempalace(args, timeout=30):
    """Call mempalace CLI or use -m module."""
    import subprocess
    env = os.environ.copy()
    
    if MEMPALACE_USE_MODULE:
        cmd = [sys.executable, '-m', 'mempalace'] + args
    else:
        cmd = [MEMPALACE_CLI] + args
    
    # Ensure python3 is first in PATH
    python_bin = os.path.dirname(sys.executable)
    env['PATH'] = f'{python_bin}:{env.get("PATH", "")}'
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return result.stdout, result.stderr, result.returncode

# ---------------------------------------------------------------------------
# Levenshtein
# ---------------------------------------------------------------------------

def levenshtein(s1, s2):
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(c1!=c2)))
        prev = curr
    return prev[-1]

def similarity(s1, s2):
    s1, s2 = s1.lower(), s2.lower()
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    return 1.0 - (levenshtein(s1, s2) / max_len)

# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def dedup_results(results, threshold=0.85):
    if not results:
        return []
    deduped = []
    for r in results:
        content = r.get('content', '')
        if any(similarity(content, e.get('content','')) > threshold for e in deduped):
            continue
        deduped.append(r)
    return deduped

# ---------------------------------------------------------------------------
# MMR Reranking
# ---------------------------------------------------------------------------

def mmr_rerank(results, query, lambda_param=0.7, limit=5):
    if not results or len(results) <= limit:
        return results
    
    selected, remaining = [], list(results)
    
    max_s = max((r.get('score', 0) for r in remaining), default=1)
    min_s = min((r.get('score', 0) for r in remaining), default=0)
    rng = max_s - min_s if max_s != min_s else 1.0
    norm = lambda r: (r.get('score', 0) - min_s) / rng
    
    while len(selected) < limit and remaining:
        best, best_idx, best_score = None, -1, -float('inf')
        for idx, item in enumerate(remaining):
            rel = norm(item)
            max_sim = max((similarity(item.get('content',''), s.get('content','')) for s in selected), default=0)
            div = 1.0 - max_sim
            mmr = lambda_param * rel + (1 - lambda_param) * div
            if mmr > best_score:
                best_score = mmr
                best = item
                best_idx = idx
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
    (r'^```\s*\n', ''),
]

def strip_metadata(text):
    for pat, replacement in STRIP_PATTERNS:
        text = re.sub(pat, replacement, text, flags=re.MULTILINE)
    return text.strip()

# ---------------------------------------------------------------------------
# Parse MemPalace Output
# ---------------------------------------------------------------------------

def parse_search_output(output):
    """Parse mempalace markdown output into structured results."""
    lines = output.strip().split('\n')
    results, current = [], []
    in_result = False
    
    for line in lines:
        if line.startswith('---') or line.startswith('==='):
            continue
        if any(x in line for x in ['Best drawer for', 'Drawer #', 'Results for']):
            if current:
                content = '\n'.join(current).strip()
                if content:
                    results.append({'content': content, 'score': 1.0, 'source': 'mempalace'})
                current = []
            continue
        if line.strip():
            current.append(line)
    
    if current:
        content = '\n'.join(current).strip()
        if content:
            results.append({'content': content, 'score': 1.0, 'source': 'mempalace'})
    
    return results

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_search(query, limit=5, use_mmr=True, dedup=True):
    out, err, code = run_mempalace(['search', query, '--results', str(limit * 3)])
    if code != 0:
        return {'status': 'error', 'error': err}
    
    results = parse_search_output(out)
    if dedup:
        results = dedup_results(results)
    if use_mmr:
        results = mmr_rerank(results, query, lambda_param=0.7, limit=limit)
    
    return {'status': 'ok', 'query': query, 'results': results}

def cmd_wake_up():
    out, err, code = run_mempalace(['wake-up'], timeout=30)
    if code == 0:
        return {'status': 'ok', 'context': out}
    return {'status': 'error', 'error': err}

def cmd_status():
    out, err, code = run_mempalace(['status'], timeout=15)
    if code == 0:
        return {'status': 'ok', 'output': out}
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
        from chromadb.config import Settings
        palace_path = os.path.expanduser('~/.mempalace/palace')
        client = chromadb.PersistentClient(path=palace_path)
        collections = client.list_collections()
        for col in collections:
            try:
                collection = client.get_collection(col.name)
                try:
                    item = collection.get(ids=[memory_id])
                    if item and item['ids']:
                        collection.delete(ids=[memory_id])
                        return {'status': 'ok', 'action': 'forget', 'id': memory_id}
                except Exception:
                    pass
            except Exception:
                pass
        return {'status': 'ok', 'action': 'forget', 'id': memory_id, 'note': 'Memory not found'}
    except Exception as e:
        return {'status': 'error', 'action': 'forget', 'error': str(e)}

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SuperMem — MemPalace + SM6')
    sub = parser.add_subparsers(dest='cmd')
    
    p = sub.add_parser('search')
    p.add_argument('query')
    p.add_argument('--limit', type=int, default=5)
    p.add_argument('--no-mmr', dest='use_mmr', action='store_false', default=True)
    p.add_argument('--no-dedup', dest='dedup', action='store_false', default=True)
    
    sub.add_parser('status')
    sub.add_parser('wake-up')
    
    p_mine = sub.add_parser('mine')
    p_mine.add_argument('--path')
    
    p_forget = sub.add_parser('forget')
    p_forget.add_argument('memory_id')
    
    args = parser.parse_args()
    
    if args.cmd == 'search':
        result = cmd_search(args.query, args.limit, args.use_mmr, args.dedup)
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
