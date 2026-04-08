// MemPalace Recall Hook v2 - Enhanced with SM6's best features
// Hook: message:preprocessed
// Features: MMR + dedup + metadata stripping

import { spawnSync } from 'node:child_process';

interface MemPalaceResult {
  status: string;
  query?: string;
  results?: Array<{
    content: string;
    score: number;
    source: string;
  }>;
  error?: string;
}

function callPython(scriptPath: string, args: string[]): string {
  try {
    const result = spawnSync('/usr/bin/python3', [scriptPath, ...args], {
      timeout: 15000,
      env: { ...process.env, PATH: `/Users/mars/Library/Python/3.9/bin:${process.env.PATH}` }
    });
    if (result.status !== 0) {
      return '';
    }
    return result.stdout.toString();
  } catch {
    return '';
  }
}

function stripMetadata(text: string): string {
  const result = callPython(
    '/Users/mars/.openclaw/workspace/skills/mempalace-memory/scripts/mempalace_reranker.py',
    ['strip', '--text', text]
  );
  try {
    const parsed = JSON.parse(result);
    return parsed.status === 'ok' ? parsed.cleaned : text;
  } catch {
    return text;
  }
}

function searchMemPalace(query: string, limit = 3): string {
  const result = callPython(
    '/Users/mars/.openclaw/workspace/skills/mempalace-memory/scripts/mempalace_cli.py',
    ['search', query, '--limit', String(limit), '--no-strip']
  );
  return result;
}

export default async function handler(event: any) {
  // Only run on messages with content
  const messages = event.messages || [];
  const lastUserMsg = [...messages].reverse().find(m => m.role === 'user');
  
  if (!lastUserMsg) return;

  // Extract user message text
  let userText = typeof lastUserMsg.content === 'string'
    ? lastUserMsg.content
    : (lastUserMsg.content?.[0]?.text || '');

  if (!userText || userText.length < 2) return;

  // Strip metadata from user text (remove [user:ou_xxx], code fences, etc.)
  const cleanQuery = stripMetadata(userText);

  // Search MemPalace
  const searchOutput = searchMemPalace(cleanQuery, 3);

  let memoryContexts: string[] = [];

  if (searchOutput) {
    try {
      const parsed: MemPalaceResult = JSON.parse(searchOutput);
      if (parsed.status === 'ok' && parsed.results && parsed.results.length > 0) {
        // Format results for injection
        for (const r of parsed.results) {
          const content = r.content.trim();
          if (content && content.length > 10) {
            memoryContexts.push(content);
          }
        }
      }
    } catch {
      // If JSON parse fails, fall back to raw output
      if (searchOutput.trim()) {
        memoryContexts.push(searchOutput.trim());
      }
    }
  }

  // Inject memory context into bodyForAgent
  if (memoryContexts.length > 0 && event.context?.bodyForAgent) {
    const memoryHeader = `\n\n🧠 **MemPalace Recall**\n${memoryContexts.join('\n---\n')}\n---\n`;
    event.context.bodyForAgent = memoryHeader + event.context.bodyForAgent;
  }

  return;
}
