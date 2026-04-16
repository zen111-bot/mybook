import json
import os
from collections.abc import Iterator

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from graphs import run_chat
from graphs.chat_graph import iter_ark_chat_stream, prepare_chat_context


class ChatMeta(BaseModel):
    latency_ms: float
    system_prompt_summary: str
    token_estimate: int

app = FastAPI(title="Agent Demo Backend", version="0.1.0")

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")
ALLOWED_ORIGINS = [o.strip() for o in FRONTEND_ORIGIN.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    agent: str = "profile"
    task: str = "general"
    message: str


class ChatResponse(BaseModel):
    agent: str
    reply: str
    meta: ChatMeta


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "agent-demo-backend"}


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    reply, meta = run_chat(agent=payload.agent, task=payload.task, message=payload.message)
    return ChatResponse(agent=payload.agent, reply=reply, meta=ChatMeta(**meta))


def _sse_pack(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.post("/chat/stream")
def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """SSE 转发方舟流式输出（Chat Completions + stream=true）。说明见官方文档流式输出章节。"""

    def event_stream() -> Iterator[str]:
        try:
            system_prompt, user_message = prepare_chat_context(
                payload.agent, payload.task, payload.message
            )
            for chunk in iter_ark_chat_stream(system_prompt, user_message):
                if chunk:
                    yield _sse_pack({"d": chunk})
            yield "data: [DONE]\n\n"
        except Exception as exc:
            yield _sse_pack({"error": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
