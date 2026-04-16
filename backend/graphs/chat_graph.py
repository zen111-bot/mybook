"""双智能体聊天工作流：路由 → 读数据（profile）→ 组装 system prompt → 调用 ARK。"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from typing import Any, Literal, NotRequired, TypedDict

import httpx
from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.path.join(BACKEND_ROOT, "data", "profile.json")

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
ARK_CHAT_URL = os.getenv(
    "ARK_CHAT_COMPLETIONS_URL",
    "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
)
ARK_MODEL = os.getenv("ARK_MODEL", "doubao-seed-2-0-mini-260215")


class ChatState(TypedDict):
    agent: str
    task: str
    message: str
    profile_data: NotRequired[dict]
    system_prompt: NotRequired[str]
    reply: NotRequired[str]


def _ecommerce_prompt(task: str) -> str:
    if task == "copywriting":
        return (
            "你是电商文案助手。请根据用户输入输出："
            "1) 商品标题（3个版本）；"
            "2) 核心卖点（3-5条）；"
            "3) 详情页短文案（80-150字）；"
            "4) 适合的目标人群。"
            "要求：实用、可直接粘贴到电商后台。"
        )
    if task == "review_analysis":
        return (
            "你是电商评论分析助手。请输出："
            "1) 评论情绪判断（正向/中性/负向）；"
            "2) 用户关注点（质量、价格、物流、服务等）；"
            "3) 主要问题Top3；"
            "4) 可执行改进建议（按优先级）。"
            "要求：结论明确，建议可落地。"
        )
    return (
        "你是电商智能体，目标是提供实用、可执行的电商建议。"
        "回答应包含明确步骤或要点，语言简洁。"
    )


def _load_profile_data() -> dict:
    if not os.path.exists(PROFILE_PATH):
        return {
            "notice": "profile.json not found",
            "next_step": "create backend/data/profile.json with personal info",
        }
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {"notice": "profile.json must be a JSON object"}
    except Exception as exc:
        return {"notice": "failed to load profile.json", "error": str(exc)}


def _extract_text(response_json: dict) -> str:
    if isinstance(response_json.get("output_text"), str) and response_json["output_text"].strip():
        return response_json["output_text"].strip()

    for item in response_json.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text"):
                text = content.get("text", "").strip()
                if text:
                    return text

    return "模型已返回结果，但未解析到文本内容。"


def route_by_agent(state: ChatState) -> Literal["profile", "ecommerce"]:
    if state.get("agent") == "ecommerce":
        return "ecommerce"
    return "profile"


def node_load_profile(state: ChatState) -> dict:
    return {"profile_data": _load_profile_data()}


def node_build_system_prompt(state: ChatState) -> dict:
    agent = state["agent"]
    task = state["task"]
    if agent == "ecommerce":
        return {"system_prompt": _ecommerce_prompt(task)}
    profile_data = state.get("profile_data") or _load_profile_data()
    profile_json = json.dumps(profile_data, ensure_ascii=False)
    return {
        "system_prompt": (
            "你是个人介绍智能体。请仅基于给定个人资料回答，不要编造经历。"
            "如果资料中没有明确答案，请直接说明并建议用户补充 profile.json。"
            f"以下是个人资料 JSON：{profile_json}"
        )
    }


def node_invoke_llm(state: ChatState) -> dict:
    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing ARK_API_KEY in environment variables.")

    system_prompt = state.get("system_prompt") or ""
    message = state["message"]

    payload = {
        "model": ARK_MODEL,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": message}]},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # 电商等长输出场景可能超过 45s，单独拉长读超时
    timeout = httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=10.0)
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(ARK_BASE_URL, headers=headers, json=payload)
        resp.raise_for_status()
        response_json = resp.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        raise HTTPException(status_code=502, detail=f"ARK API error: {detail}") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="ARK API 响应超时（模型生成较慢或网络不稳），请稍后重试。",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to call ARK API: {exc}") from exc

    reply = _extract_text(response_json)
    if not reply:
        reply = json.dumps(response_json, ensure_ascii=False)[:1000]
    return {"reply": reply}


def build_chat_graph() -> StateGraph:
    graph = StateGraph(ChatState)
    graph.add_node("load_profile", node_load_profile)
    graph.add_node("build_system_prompt", node_build_system_prompt)
    graph.add_node("invoke_llm", node_invoke_llm)

    graph.add_conditional_edges(
        START,
        route_by_agent,
        {
            "profile": "load_profile",
            "ecommerce": "build_system_prompt",
        },
    )
    graph.add_edge("load_profile", "build_system_prompt")
    graph.add_edge("build_system_prompt", "invoke_llm")
    graph.add_edge("invoke_llm", END)
    return graph


_compiled = build_chat_graph().compile()


def prepare_chat_context(agent: str, task: str, message: str) -> tuple[str, str]:
    """与 LangGraph 一致：组装 system prompt + user 文本（供流式 Chat Completions 使用）。"""
    state: ChatState = {"agent": agent, "task": task, "message": message}
    if agent != "ecommerce":
        state.update(node_load_profile(state))
    state.update(node_build_system_prompt(state))
    return (state.get("system_prompt") or "").strip(), message


def iter_ark_chat_stream(system_prompt: str, user_message: str) -> Iterator[str]:
    """方舟 Chat API 流式调用（与官方说明一致：stream=true，SSE，delta.content / reasoning_content）。

    文档：https://www.volcengine.com/docs/82379/2123275?lang=zh
    非流式图节点仍走 Responses API（/responses）；流式为独立路径，使用 /chat/completions。
    """
    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ARK_API_KEY in environment variables.")

    payload = {
        "model": ARK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=10.0)

    content_parts: list[str] = []
    reasoning_parts: list[str] = []

    with httpx.Client(timeout=timeout) as client:
        with client.stream("POST", ARK_CHAT_URL, headers=headers, json=payload) as resp:
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:4000]
                raise RuntimeError(detail or f"ARK HTTP {exc.response.status_code}") from exc

            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj: dict[str, Any] = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if isinstance(delta, dict):
                    c = delta.get("content")
                    if isinstance(c, str) and c:
                        content_parts.append(c)
                        yield c
                    r = delta.get("reasoning_content")
                    if isinstance(r, str) and r:
                        reasoning_parts.append(r)

    if not "".join(content_parts).strip() and "".join(reasoning_parts).strip():
        yield "".join(reasoning_parts)


def run_chat(agent: str, task: str, message: str) -> tuple[str, dict[str, Any]]:
    t0 = time.perf_counter()
    final: ChatState = _compiled.invoke(
        {
            "agent": agent,
            "task": task,
            "message": message,
        }
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    reply = final.get("reply")
    if not reply:
        raise HTTPException(status_code=500, detail="Graph finished without reply.")
    sp = final.get("system_prompt") or ""
    summary = sp[:400] + ("…" if len(sp) > 400 else "")
    approx_tokens = max(1, (len(sp) + len(message) + len(reply)) // 4)
    meta: dict[str, Any] = {
        "latency_ms": round(latency_ms, 1),
        "system_prompt_summary": summary,
        "token_estimate": approx_tokens,
    }
    return reply, meta
