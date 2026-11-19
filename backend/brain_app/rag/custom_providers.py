"""Provider AI tùy chỉnh, tương thích chuẩn OpenAI (/chat/completions).

Dùng được với NVIDIA NIM, DeepSeek, Groq, Together, Mistral, vLLM, Ollama, LM Studio... bất kỳ máy chủ
nào nói chuẩn OpenAI. Cấu hình lưu trong bảng settings (khoá 'custom_providers', dạng JSON).

Quy ước:
  * Provider được chọn dưới dạng 'custom:<id>' (cùng chỗ với 'gemini' / 'openrouter').
  * API key KHÔNG BAO GIỜ được trả về qua API: chỉ trả has_key + key_masked.
  * API key có thể để trống (Ollama / LM Studio chạy trên máy không cần key).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from brain_app.database import get_db_connection

SETTING_KEY = "custom_providers"
MAX_PROVIDERS = 12
MAX_MODELS = 200
_transport: Optional[httpx.AsyncBaseTransport] = None  # tests inject a mock here

PRESETS = [
    {"name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1", "needs_key": True,
     "example_model": "meta/llama-3.3-70b-instruct"},
    {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "needs_key": True, "example_model": "deepseek-chat"},
    {"name": "Groq", "base_url": "https://api.groq.com/openai/v1", "needs_key": True,
     "example_model": "llama-3.3-70b-versatile"},
    {"name": "Ollama (trên máy)", "base_url": "http://localhost:11434/v1", "needs_key": False, "example_model": "llama3.1"},
    {"name": "LM Studio (trên máy)", "base_url": "http://localhost:1234/v1", "needs_key": False, "example_model": ""},
]


class CustomProviderError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# --------------------------------------------------------------------------- lưu trữ

def _load() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (SETTING_KEY,)).fetchone()
    finally:
        conn.close()
    if not row or not row["value"]:
        return []
    try:
        data = json.loads(row["value"])
        return [p for p in data if isinstance(p, dict) and p.get("id")]
    except Exception:
        return []


def _save(providers: List[Dict[str, Any]]):
    conn = get_db_connection()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                     (SETTING_KEY, json.dumps(providers, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def _mask(key: str) -> str:
    if not key:
        return ""
    return key[:4] + "*" * max(len(key) - 8, 4) + key[-4:] if len(key) > 8 else "****"


def public(p: Dict[str, Any]) -> Dict[str, Any]:
    """Dạng an toàn để gửi ra giao diện (không có api_key)."""
    return {
        "id": p["id"], "name": p["name"], "base_url": p["base_url"],
        "models": p.get("models", []), "default_model": p.get("default_model", ""),
        "json_mode": p.get("json_mode", "auto"),
        "has_key": bool(p.get("api_key")), "key_masked": _mask(p.get("api_key", "")),
    }


def list_providers() -> List[Dict[str, Any]]:
    return [public(p) for p in _load()]


def get(provider_id: str) -> Optional[Dict[str, Any]]:
    for p in _load():
        if p["id"] == provider_id:
            return p
    return None


def exists(provider_ref: str) -> bool:
    """provider_ref có dạng 'custom:<id>'."""
    return provider_ref.startswith("custom:") and get(provider_ref[7:]) is not None


# --------------------------------------------------------------------------- kiểm tra dữ liệu

def normalize_base_url(url: str) -> str:
    url = (url or "").strip()
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise CustomProviderError("Base URL phải bắt đầu bằng http:// hoặc https://, ví dụ https://api.example.com/v1")
    url = url.rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url.rstrip("/")


def _slug(name: str, taken: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "provider"
    slug, n = base, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    return slug


def _clean_models(models: Any) -> List[str]:
    seen, out = set(), []
    for m in models or []:
        mid = (m.get("id") if isinstance(m, dict) else str(m or "")).strip()
        if mid and mid not in seen and len(mid) <= 200:
            seen.add(mid)
            out.append(mid)
    return out[:MAX_MODELS]


def upsert(data: Dict[str, Any]) -> Dict[str, Any]:
    """Tạo mới (không có id) hoặc cập nhật (có id). api_key=None nghĩa là giữ key cũ."""
    providers = _load()
    name = (data.get("name") or "").strip()[:60]
    if not name:
        raise CustomProviderError("Cần đặt tên cho provider")
    base_url = normalize_base_url(data.get("base_url", ""))
    models = _clean_models(data.get("models"))
    default_model = (data.get("default_model") or "").strip()[:200]
    if default_model and default_model not in models:
        models.insert(0, default_model)
    if not models:
        raise CustomProviderError("Cần ít nhất 1 model (nhập ID model hoặc bấm “Lấy danh sách model”)")
    if not default_model:
        default_model = models[0]
    json_mode = data.get("json_mode", "auto")
    if json_mode not in ("auto", "off"):
        raise CustomProviderError("json_mode phải là 'auto' hoặc 'off'")

    pid = data.get("id")
    existing = next((p for p in providers if p["id"] == pid), None) if pid else None
    if pid and not existing:
        raise CustomProviderError("Không tìm thấy provider", 404)
    if any(p["name"].lower() == name.lower() and p["id"] != pid for p in providers):
        raise CustomProviderError(f"Đã có provider tên '{name}'", 409)
    if not existing and len(providers) >= MAX_PROVIDERS:
        raise CustomProviderError(f"Tối đa {MAX_PROVIDERS} provider tùy chỉnh")

    api_key = data.get("api_key")
    key = (existing.get("api_key", "") if existing else "") if api_key is None else api_key.strip()
    record = {"id": existing["id"] if existing else _slug(name, {p["id"] for p in providers}),
              "name": name, "base_url": base_url, "api_key": key,
              "models": models, "default_model": default_model, "json_mode": json_mode}
    if existing:
        providers = [record if p["id"] == existing["id"] else p for p in providers]
    else:
        providers.append(record)
    _save(providers)
    return public(record)


def delete(provider_id: str):
    providers = _load()
    if not any(p["id"] == provider_id for p in providers):
        raise CustomProviderError("Không tìm thấy provider", 404)
    _save([p for p in providers if p["id"] != provider_id])


# --------------------------------------------------------------------------- dùng khi gọi AI

def active_cfg(provider_id: str) -> Optional[Dict[str, Any]]:
    """Cấu hình đầy đủ (có key) để gọi AI; chỉ dùng nội bộ ở backend."""
    p = get(provider_id)
    if not p:
        return None
    headers = {"Content-Type": "application/json"}
    if p.get("api_key"):
        headers["Authorization"] = f"Bearer {p['api_key']}"
    return {"provider": "custom", "id": p["id"], "label": p["name"], "key": p.get("api_key", ""),
            "model": p.get("default_model") or (p.get("models") or [""])[0],
            "chat_url": f"{p['base_url']}/chat/completions", "headers": headers,
            "json_mode": p.get("json_mode", "auto")}


def _err_text(resp: httpx.Response) -> str:
    try:
        j = resp.json()
        msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else (j.get("error") or j.get("detail"))
    except Exception:
        msg = ""
    return str(msg or resp.text[:300])


async def fetch_models(provider_id: str) -> List[Dict[str, str]]:
    cfg = active_cfg(provider_id)
    p = get(provider_id)
    if not cfg or not p:
        raise CustomProviderError("Không tìm thấy provider", 404)
    async with httpx.AsyncClient(timeout=20.0, transport=_transport) as client:
        resp = await client.get(f"{p['base_url']}/models", headers=cfg["headers"])
    if resp.status_code != 200:
        raise CustomProviderError(f"Máy chủ trả về {resp.status_code}: {_err_text(resp)}", 502)
    data = resp.json()
    items = data.get("data") if isinstance(data, dict) else data
    out = []
    for m in items or []:
        mid = m.get("id") if isinstance(m, dict) else str(m)
        if mid:
            out.append({"id": mid, "name": mid, "desc": (m.get("owned_by") or "") if isinstance(m, dict) else ""})
    if not out:
        raise CustomProviderError("Máy chủ không trả về danh sách model nào", 502)
    return out


async def list_models(provider_id: str, refresh: bool = False) -> Dict[str, Any]:
    """Danh sách model cho giao diện: model bạn đã khai báo + (nếu máy chủ hỗ trợ) danh sách trực tuyến."""
    p = get(provider_id)
    if not p:
        raise CustomProviderError("Không tìm thấy provider", 404)
    configured = [{"id": m, "name": m, "desc": "đã khai báo"} for m in p.get("models", [])]
    try:
        live = await fetch_models(provider_id)
        known = {m["id"] for m in configured}
        models = configured + [m for m in live if m["id"] not in known]
        return {"provider": f"custom:{provider_id}", "source": "live", "models": models, "error": None}
    except Exception as e:  # noqa: BLE001 - máy chủ không có /models vẫn dùng được danh sách đã khai báo
        msg = e.message if isinstance(e, CustomProviderError) else str(e)
        return {"provider": f"custom:{provider_id}", "source": "configured", "models": configured,
                "error": f"Không lấy được danh sách trực tuyến ({msg}). Đang dùng danh sách bạn đã khai báo."}


async def test(provider_id: str, model: Optional[str] = None) -> Dict[str, Any]:
    """Gửi một câu hỏi rất ngắn để kiểm tra địa chỉ, key và model có chạy không."""
    cfg = active_cfg(provider_id)
    if not cfg:
        raise CustomProviderError("Không tìm thấy provider", 404)
    use_model = (model or cfg["model"]).strip()
    body = {"model": use_model, "max_tokens": 16, "temperature": 0,
            "messages": [{"role": "user", "content": "Trả lời đúng một chữ: OK"}]}
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=60.0, transport=_transport) as client:
            resp = await client.post(cfg["chat_url"], headers=cfg["headers"], json=body)
    except httpx.HTTPError as e:
        return {"ok": False, "model": use_model, "error": f"Không kết nối được: {e}"}
    ms = int((time.time() - started) * 1000)
    if resp.status_code != 200:
        hint = ""
        if resp.status_code in (401, 403):
            hint = " Kiểm tra lại API key."
        elif resp.status_code == 404:
            hint = " Kiểm tra Base URL và tên model."
        return {"ok": False, "model": use_model, "latency_ms": ms, "error": f"Lỗi {resp.status_code}: {_err_text(resp)}.{hint}"}
    try:
        reply = (resp.json()["choices"][0]["message"].get("content") or "").strip()
    except Exception:
        return {"ok": False, "model": use_model, "latency_ms": ms, "error": "Phản hồi không đúng chuẩn OpenAI (thiếu choices[0].message)."}
    return {"ok": True, "model": use_model, "latency_ms": ms, "reply": reply[:80]}
