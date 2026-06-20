"""FastAPI backend for the poe2-mcp web UI.

Two surfaces:
  - REST endpoints (/api/load, /api/archetype, /api/class-tree) call the analysis
    library directly — no LLM, no API key, free and deterministic. These power the
    structured panels.
  - /api/chat streams a Claude conversation that drives the poe2 MCP server over
    stdio (Anthropic Messages API + the SDK's MCP tool bridge). Needs
    ANTHROPIC_API_KEY and `pip install "anthropic[mcp]"`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import analysis

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = Path(__file__).resolve().parent / ".env"  # gitignored; holds ANTHROPIC_API_KEY


def _api_key() -> str | None:
    """Anthropic key from the environment, else from webui/backend/.env (read fresh)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY"):
                _, _, val = line.partition("=")
                return val.strip().strip("'\"") or None
    return None

app = FastAPI(title="poe2-mcp web UI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# REST — structured panels (direct calls, no LLM)
# --------------------------------------------------------------------------- #

class LoadBody(BaseModel):
    code: str  # PoB export code, pobb.in URL, or local file path


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "chat_enabled": bool(_api_key())}


@app.post("/api/load")
def load(body: LoadBody) -> dict:
    try:
        return analysis.load_build(body.code.strip())
    except Exception as e:  # decode/parse errors → clean message for the UI
        return {"error": str(e)}


@app.get("/api/archetype")
def archetype(skill: str, support_builds: int = 12, core_threshold: float = 0.6) -> dict:
    return analysis.analyze_archetype(skill, support_builds=support_builds,
                                      core_threshold=core_threshold)


@app.get("/api/class-tree")
def class_tree(class_name: str, scan_limit: int = 80, core_threshold: float = 0.6) -> dict:
    return analysis.analyze_class_tree(class_name, scan_limit=scan_limit,
                                       core_threshold=core_threshold)


# --------------------------------------------------------------------------- #
# Chat — Claude + the poe2 MCP server (SSE stream)
# --------------------------------------------------------------------------- #

class ChatBody(BaseModel):
    messages: list[dict]      # [{role, content}], content is a string
    api_key: str | None = None  # optional: key entered in the web UI (browser-stored)


_SYSTEM = (
    "You are a Path of Exile 2 build assistant embedded in a web app. The user is "
    "viewing structured panels (build stats, archetype core/tech, class tree) and "
    "may ask follow-up questions. Use the poe2 tools to ground every answer; never "
    "recite game mechanics from memory. Be concise and lead with the conclusion."
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _chat_events(messages: list[dict], api_key: str | None = None):
    key = api_key or _api_key()
    if not key:
        yield _sse("error", {"message": "No Anthropic key — paste one into the field above."})
        return
    try:
        from anthropic import AsyncAnthropic
        from anthropic.lib.tools.mcp import async_mcp_tool
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
    except ImportError:
        yield _sse("error", {"message": 'Install chat deps: uv pip install "anthropic[mcp]"'})
        return

    client = AsyncAnthropic(api_key=key)
    params = StdioServerParameters(command="uv", args=["run", "poe2-mcp"], cwd=str(REPO_ROOT))
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as mcp_client:
                init = await mcp_client.initialize()
                system = _SYSTEM
                if getattr(init, "instructions", None):  # the server's review principles
                    system += "\n\n" + init.instructions
                tools = [async_mcp_tool(t, mcp_client)
                         for t in (await mcp_client.list_tools()).tools]

                runner = client.beta.messages.tool_runner(
                    model="claude-sonnet-4-6",
                    max_tokens=8000,
                    thinking={"type": "adaptive"},
                    system=system,
                    tools=tools,
                    messages=messages,
                )
                async for message in runner:
                    for block in message.content:
                        if block.type == "text" and block.text:
                            yield _sse("text", {"text": block.text})
                        elif block.type == "tool_use":
                            yield _sse("tool", {"name": block.name})
        yield _sse("done", {})
    except Exception as e:
        yield _sse("error", {"message": str(e)})


@app.post("/api/chat")
async def chat(body: ChatBody) -> StreamingResponse:
    return StreamingResponse(
        _chat_events(body.messages, body.api_key), media_type="text/event-stream"
    )
