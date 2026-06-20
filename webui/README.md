# PoE2 Build Lab — web UI

A hybrid web front end for `poe2-mcp`:

- **Panels** (free, no LLM) — Load a build, inspect stats/defenses/items/skills, and
  run the **Archetype** (core vs tech skills, supports, tree, gear) and **Class Tree**
  analyses. These call the Python analysis library directly.
- **Chat** (optional, billed) — a Claude conversation that drives the poe2 MCP server
  over stdio. Needs `ANTHROPIC_API_KEY`.

```
Browser (React)  ──HTTP/SSE──►  FastAPI backend  ──► analysis library (panels)
                                       │
                                       └──anthropic[mcp] stdio──►  poe2-mcp server (chat)
```

## Backend

From the repo root:

```bash
uv pip install -r webui/backend/requirements.txt        # fastapi, uvicorn (+ anthropic[mcp] for chat)
uv run uvicorn app:app --app-dir webui/backend --reload --port 8000
```

For the chat panel, also export a key before starting: `export ANTHROPIC_API_KEY=sk-ant-...`
(Chat uses Claude Opus 4.8 with adaptive thinking; the panels need no key.)

## Frontend

```bash
cd webui/frontend
npm install
npm run dev          # http://localhost:5173
```

The dev server expects the backend at `http://localhost:8000` (override with
`VITE_API_BASE`). `npm run build` produces a static bundle in `dist/`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/health` | liveness + whether chat is enabled |
| POST | `/api/load` | `{code}` → stats, defenses, items, skills, passives |
| GET  | `/api/archetype?skill=&support_builds=` | core/tech skills, supports, tree, gear |
| GET  | `/api/class-tree?class_name=&scan_limit=` | core/tech passive tree nodes |
| POST | `/api/chat` | SSE stream of a Claude + MCP conversation |

## Notes

- The panels are stateless. The chat bridge spawns `uv run poe2-mcp` per request and
  injects the server's review principles (from the MCP `initialize` result) into the
  system prompt.
- The cohort analyses fetch ladder builds from poe.ninja (cached ~15 min); the first
  call of each can take a few seconds.
