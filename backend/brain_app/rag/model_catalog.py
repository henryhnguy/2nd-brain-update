"""Live chat-model lists (Gemini + OpenRouter) with a static fallback.

Model names change every few months (Gemini 1.5 / 2.0 are already gone), so the app asks the
providers what exists today instead of trusting a hard-coded list. If the lookup fails
(offline, bad key) the static fallback is returned and flagged as such.
"""
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from brain_app.rag.embeddings import GEMINI_BASE, embedding_service

CACHE_TTL = 600  # seconds
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_transport: Optional[httpx.AsyncBaseTransport] = None  # tests inject a mock here

# Fallbacks (as listed in Google's deprecation page, Oct 2026). Used only when the live lookup fails.
GEMINI_FALLBACK: List[Dict[str, str]] = [
    {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash", "desc": "Mới nhất, nhanh (mặc định)"},
    {"id": "gemini-3.6-flash", "name": "Gemini 3.6 Flash", "desc": "Nhanh, ổn định"},
    {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash-Lite", "desc": "Nhẹ, quota thoải mái"},
    {"id": "gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro (preview)", "desc": "Suy luận sâu hơn"},
    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "desc": "Bản cũ, có thể bị giới hạn với key mới"},
    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "desc": "Bản cũ, có thể bị giới hạn với key mới"},
]
DEFAULT_GEMINI_CHAT_MODEL = GEMINI_FALLBACK[0]["id"]

OPENROUTER_FALLBACK: List[Dict[str, str]] = [
    {"id": "openrouter/auto", "name": "OpenRouter Auto", "desc": "Tự chọn model phù hợp"},
    {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3", "desc": "Rẻ, thông minh"},
    {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1", "desc": "Suy luận chuyên sâu"},
    {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "desc": "Nhanh, rẻ"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "desc": "Mã nguồn mở"},
    {"id": "qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B", "desc": "Đa ngôn ngữ"},
]

_GEMINI_EXCLUDE = ("tts", "image", "live", "embedding", "robotics", "omni", "computer-use",
                   "transcribe", "imagen", "veo", "lyria", "aqa", "native-audio", "banana", "gemma")


def _version_key(model_id: str):
    nums = re.findall(r"\d+(?:\.\d+)?", model_id)
    return -float(nums[0]) if nums else 0.0


def _parse_gemini(data: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for m in data.get("models", []):
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        mid = (m.get("name") or "").replace("models/", "")
        if not mid.startswith("gemini") or any(x in mid for x in _GEMINI_EXCLUDE):
            continue
        out.append({
            "id": mid,
            "name": m.get("displayName") or mid,
            "desc": ((m.get("description") or "").split(". ")[0])[:90],
        })
    # newest version first, then flash before pro, stable before preview
    out.sort(key=lambda x: (_version_key(x["id"]), "preview" in x["id"], x["id"]))
    return out


def _parse_openrouter(data: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for m in data.get("data", []):
        arch = m.get("architecture") or {}
        outputs = arch.get("output_modalities")
        if outputs is not None and "text" not in outputs:
            continue
        mid = m.get("id")
        if not mid:
            continue
        ctx = m.get("context_length") or 0
        pricing = m.get("pricing") or {}
        free = str(pricing.get("prompt", "")) in ("0", "0.0") and str(pricing.get("completion", "")) in ("0", "0.0")
        desc = f"{ctx // 1000}k ngữ cảnh" if ctx else ""
        if free:
            desc = (desc + " · " if desc else "") + "miễn phí"
        out.append({"id": mid, "name": m.get("name") or mid, "desc": desc})
    return out[:500]


async def _fetch(provider: str) -> List[Dict[str, str]]:
    async with httpx.AsyncClient(timeout=20.0, transport=_transport) as client:
        if provider == "gemini":
            key = embedding_service.gemini_key()
            if not key:
                raise RuntimeError("Chưa có Gemini API Key.")
            resp = await client.get(f"{GEMINI_BASE}/models", params={"pageSize": 1000},
                                    headers={"x-goog-api-key": key})
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini trả về {resp.status_code}")
            return _parse_gemini(resp.json())
        resp = await client.get("https://openrouter.ai/api/v1/models")
        if resp.status_code != 200:
            raise RuntimeError(f"OpenRouter trả về {resp.status_code}")
        return _parse_openrouter(resp.json())


async def list_models(provider: str, refresh: bool = False) -> Dict[str, Any]:
    if provider.startswith("custom:"):
        from brain_app.rag import custom_providers  # tránh import vòng
        try:
            return await custom_providers.list_models(provider[7:], refresh)
        except custom_providers.CustomProviderError as e:
            raise ValueError(e.message)
    if provider not in ("gemini", "openrouter"):
        raise ValueError("provider phải là 'gemini', 'openrouter' hoặc 'custom:<id>'")
    cache_key = provider + (":" + embedding_service.gemini_key()[-6:] if provider == "gemini" else "")
    hit = _cache.get(cache_key)
    if hit and not refresh and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    fallback = GEMINI_FALLBACK if provider == "gemini" else OPENROUTER_FALLBACK
    try:
        models = await _fetch(provider)
        if not models:
            raise RuntimeError("Danh sách rỗng")
        result = {"provider": provider, "source": "live", "models": models, "error": None}
        _cache[cache_key] = (time.time(), result)  # only successful lookups are cached
        return result
    except Exception as e:
        return {"provider": provider, "source": "fallback", "models": fallback,
                "error": f"Không lấy được danh sách trực tuyến ({e}). Đang dùng danh sách dự phòng."}
