"""FastAPI 后端：session / provider / chat(SSE) API，供 web 与 desktop 复用。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "core"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.loop import Agent
from agent.memory import EbbinghausMemory
from agent.modes import Mode
from agent.providers import ProviderRegistry
from agent.session import SessionStore

app = FastAPI(title="agent-server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = SessionStore()
registry = ProviderRegistry()
memory = EbbinghausMemory()

# 每个 session 的运行时状态（单用户本地服务，内存即可）
session_state: dict[str, dict] = {}


def _state(session_id: str) -> dict:
    if session_id not in session_state:
        session_state[session_id] = {
            "provider": registry.names()[0],
            "model": None,  # None = 用供应商默认模型
            "mode": Mode.ACT,
        }
    return session_state[session_id]


class ChatRequest(BaseModel):
    session_id: str
    message: str
    provider: str | None = None
    model: str | None = None
    mode: str | None = None


class SessionCreate(BaseModel):
    title: str = "新会话"


# ---------- 供应商 ----------

@app.get("/api/providers")
def get_providers():
    return {
        "providers": [
            {"name": n, "models": registry.models(n), "default_model": registry.default_model(n)}
            for n in registry.names()
        ]
    }


# ---------- 会话 ----------

@app.get("/api/sessions")
def list_sessions():
    return {"sessions": [
        {"id": s.id, "title": s.title, "updated_at": s.updated_at}
        for s in store.list()
    ]}


@app.post("/api/sessions")
def create_session(body: SessionCreate):
    s = store.create(title=body.title)
    return {"id": s.id, "title": s.title}


@app.get("/api/sessions/search")
def search_sessions(q: str):
    return {"hits": [
        {"id": s.id, "title": s.title, "snippet": snippet, "updated_at": s.updated_at}
        for s, snippet in store.search(q)
    ]}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    s = store.load(session_id)
    # 只返回 user/assistant 文本消息供渲染
    msgs = [
        {"role": m["role"], "content": m.get("content", "")}
        for m in s.messages
        if m["role"] in ("user", "assistant") and m.get("content")
    ]
    st = _state(session_id)
    return {
        "id": s.id, "title": s.title, "messages": msgs,
        "state": {"provider": st["provider"],
                  "model": st["model"] or registry.default_model(st["provider"]),
                  "mode": st["mode"].value},
    }


# ---------- 对话（SSE） ----------

@app.post("/api/chat")
def chat(body: ChatRequest):
    st = _state(body.session_id)
    if body.provider:
        st["provider"] = body.provider
        st["model"] = None  # 换供应商后回落默认模型
    if body.model:
        st["model"] = body.model
    if body.mode:
        st["mode"] = Mode.parse(body.mode)

    session = store.load(body.session_id)
    provider = st["provider"]
    agent = Agent(
        client=registry.client(provider),
        model=st["model"] or registry.default_model(provider),
        mode=st["mode"],
        memory=memory,
        messages=session.messages or None,
        session_id=session.id,
        on_message=lambda m: store.append(session.id, m),
    )

    def stream():
        for ev in agent.run_turn(body.message):
            yield f"data: {json.dumps({'kind': ev.kind, **ev.data}, ensure_ascii=False)}\n\n"
        # 首轮自动命名
        if session.title == "新会话":
            store.rename(session.id, body.message[:20])

    return StreamingResponse(stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8899)
