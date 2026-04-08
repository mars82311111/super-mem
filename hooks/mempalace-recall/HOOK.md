---
name: mempalace-recall
description: "MemPalace automatic recall — searches relevant memories before every response"
metadata:
  openclaw:
    emoji: "🧠"
    events: ["message:preprocessed"]
    requires:
      bins: ["node", "python3"]
---

# MemPalace Recall Hook

Automatically searches MemPalace for relevant memories before every model response, injecting context into `bodyForAgent`.

## How it works

1. Hook fires on `message:preprocessed` (after all media/link understanding)
2. Extracts user message text from `context.bodyForAgent`
3. Calls mempalace CLI search with the message
4. Prepends memory results to `bodyForAgent` for the model

## Configuration

- CLI path: `/Users/mars/Library/Python/3.9/bin/mempalace`
- Search limit: 3 results
- Workspace: `~/.openclaw/workspace`

## Memory integration

This hook makes MemPalace fully automatic — no manual recall needed on every message.
