"""Provider-agnostic text generation (Gemini or OpenRouter) used by Studio.

The chat/RAG path has its own provider code; this module is the generic "system prompt in,
text (or JSON) out" primitive. All failures raise LLMError with a message fit for the UI.
"""
import asyncio
import json
import os
import re
from typing import Any, Dict, Optional

import httpx

from brain_app.database import get_db_connection
from brain_app.rag.embeddings import GEMINI_BASE
from brain_app.rag.model_catalog import DEFAULT_GEMINI_CHAT_MODEL

_transport: Optional[httpx.AsyncBaseTransport] = None  # tests inject a mock here


class LLMError(Exception):
    pass


async def _sleep(seconds: float):
    await asyncio.sleep(seconds)


def _setting(key: str, default: str = "") -> str:
    conn = get_db_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row and row["value"] is not None else default


def resolve() -> Dict[str, str]:
    """Which provider/model/key to use, from saved settings. provider '' means not configured."""
    provider = (_setting("llm_provider", "gemini") or "gemini").lower()
    if provider == "openrouter":
        key = _setting("openrouter_api_key", "").strip()
        model = _setting("openrouter_model", "") or "deepseek/deepseek-chat"
        return {"provider": "openrouter" if len(key) > 5 else "", "model": model, "key": key}
    key = (_setting("gemini_api_key", "") or os.getenv("GEMINI_API_KEY", "")).strip()
    model = _setting("gemini_model", "") or _setting("model_name", "") or DEFAULT_GEMINI_CHAT_MODEL
    return {"provider": "gemini" if len(key) > 10 else "", "model": model, "key": key}


def is_configured() -> bool:
    return bool(resolve()["provider"])


def extract_json(text: str) -> Any:
    """Parse JSON out of an LLM reply (tolerates ``` fences and surrounding prose)."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
    if starts:
        start = min(starts)
        end = max(t.rfind("}"), t.rfind("]"))
        if end > start:
            try:
                return json.loads(t[start:end + 1])
            except Exception:
                pass
    raise LLMError("Mô hình không trả về JSON hợp lệ.")


async def complete(system: str, user: str, *, json_mode: bool = False, temperature: float = 0.4,
                   max_tokens: int = 8192) -> str:
    cfg = resolve()
    if not cfg["provider"]:
        raise LLMError("Chưa cấu hình API key cho mô hình AI (Cài đặt → Google Gemini hoặc OpenRouter).")
    if cfg["provider"] == "gemini":
        return await _gemini(cfg, system, user, json_mode, temperature, max_tokens)
    return await _openrouter(cfg, system, user, json_mode, temperature, max_tokens)


async def complete_json(system: str, user: str, **kw) -> Any:
    """complete() + parse; on malformed JSON ask the model once to repair its answer."""
    text = await complete(system, user, json_mode=True, temperature=kw.pop("temperature", 0.2), **kw)
    try:
        return extract_json(text)
    except LLMError:
        text = await complete(
            system, user + "\n\nLƯU Ý: lần trước bạn trả lời sai định dạng. Chỉ trả về JSON hợp lệ, không thêm chữ nào khác.",
            json_mode=True, temperature=0.0, **kw)
        return extract_json(text)


async def _post_with_retry(client, url, headers, body, name):
    resp = None
    for attempt in range(4):
        try:
            resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as e:
            if attempt == 3:
                raise LLMError(f"Không kết nối được {name}: {e}")
            await _sleep(2 ** attempt)
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            await _sleep(min(2 ** attempt * 2, 20))
            continue
        break
    return resp


def _err_text(resp: httpx.Response) -> str:
    try:
        j = resp.json()
        msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("error")
    except Exception:
        msg = ""
    return str(msg or resp.text[:300])


async def _gemini(cfg, system, user, json_mode, temperature, max_tokens) -> str:
    url = f"{GEMINI_BASE}/models/{cfg['model']}:generateContent"
    gen: Dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen}
    async with httpx.AsyncClient(timeout=180.0, transport=_transport) as client:
        resp = await _post_with_retry(client, url, {"x-goog-api-key": cfg["key"]}, body, "Gemini")
    if resp.status_code != 200:
        hint = " Model có thể đã ngừng hỗ trợ — đổi model trong Cài đặt." if resp.status_code == 404 else ""
        raise LLMError(f"Gemini lỗi {resp.status_code}: {_err_text(resp)}.{hint}")
    data = resp.json()
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "không rõ")
        raise LLMError(f"Gemini không trả về nội dung (lý do: {reason}).")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise LLMError(f"Gemini trả về nội dung rỗng (finishReason: {cands[0].get('finishReason', '?')}).")
    return text


async def _openrouter(cfg, system, user, json_mode, temperature, max_tokens) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {cfg['key']}", "HTTP-Referer": "http://localhost:8000",
               "X-Title": "Second Brain AI", "Content-Type": "application/json"}
    body: Dict[str, Any] = {"model": cfg["model"], "temperature": temperature, "max_tokens": max_tokens,
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=180.0, transport=_transport) as client:
        resp = await _post_with_retry(client, url, headers, body, "OpenRouter")
        if resp.status_code == 400 and json_mode:  # some models reject response_format: retry plain
            body.pop("response_format", None)
            resp = await _post_with_retry(client, url, headers, body, "OpenRouter")
    if resp.status_code != 200:
        raise LLMError(f"OpenRouter lỗi {resp.status_code}: {_err_text(resp)}")
    try:
        text = resp.json()["choices"][0]["message"]["content"] or ""
    except Exception:
        raise LLMError("OpenRouter trả về phản hồi không đúng định dạng.")
    if not text.strip():
        raise LLMError("OpenRouter trả về nội dung rỗng.")
    return text
