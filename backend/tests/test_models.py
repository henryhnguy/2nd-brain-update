import asyncio

import httpx

from brain_app.rag import model_catalog
from brain_app.rag.rag_service import rag_service
from tests.conftest import set_setting

KEY = "AIzaSy-test-key-1234567890"


def run(c):
    return asyncio.run(c)


GEMINI_LIST = {"models": [
    {"name": "models/gemini-3.8-flash", "displayName": "Gemini 3.8 Flash",
     "description": "Fast model. More text.", "supportedGenerationMethods": ["generateContent", "countTokens"]},
    {"name": "models/gemini-3.1-pro-preview", "displayName": "Gemini 3.1 Pro Preview",
     "description": "Pro", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.5-flash-lite", "displayName": "Gemini 3.5 Flash-Lite",
     "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.8-flash-tts", "displayName": "TTS", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-embedding-2", "displayName": "Emb", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-3.8-live", "displayName": "Live", "supportedGenerationMethods": ["bidiGenerateContent"]},
    {"name": "models/gemma-3-27b", "displayName": "Gemma", "supportedGenerationMethods": ["generateContent"]},
]}
OR_LIST = {"data": [
    {"id": "vendor/text-model", "name": "Text Model", "context_length": 128000,
     "architecture": {"output_modalities": ["text"]}, "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
    {"id": "vendor/free-model:free", "name": "Free", "context_length": 32000,
     "architecture": {"output_modalities": ["text"]}, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "vendor/image-model", "name": "Img", "architecture": {"output_modalities": ["image"]}},
]}


def setup_transport(monkeypatch, handler):
    monkeypatch.setattr(model_catalog, "_transport", httpx.MockTransport(handler))
    model_catalog._cache.clear()


def test_gemini_live_list_filters_and_orders(db, monkeypatch):
    set_setting("gemini_api_key", KEY)
    seen = {}

    def handler(req):
        seen["key_header"] = req.headers.get("x-goog-api-key")
        seen["url"] = str(req.url)
        return httpx.Response(200, json=GEMINI_LIST)

    setup_transport(monkeypatch, handler)
    out = run(model_catalog.list_models("gemini"))
    ids = [m["id"] for m in out["models"]]
    assert out["source"] == "live"
    assert ids[0] == "gemini-3.8-flash" and "gemini-3.1-pro-preview" in ids
    assert not any(x in " ".join(ids) for x in ("tts", "embedding", "live", "gemma"))
    assert seen["key_header"] == KEY and KEY not in seen["url"]


def test_gemini_without_key_falls_back_and_says_so(db, monkeypatch):
    setup_transport(monkeypatch, lambda req: httpx.Response(500))
    out = run(model_catalog.list_models("gemini"))
    assert out["source"] == "fallback" and "API Key" in out["error"]
    assert out["models"][0]["id"] == "gemini-3.8-flash"
    assert not any("1.5" in m["id"] for m in out["models"])


def test_openrouter_live_list_text_only_and_free_flag(db, monkeypatch):
    setup_transport(monkeypatch, lambda req: httpx.Response(200, json=OR_LIST))
    out = run(model_catalog.list_models("openrouter"))
    assert [m["id"] for m in out["models"]] == ["vendor/text-model", "vendor/free-model:free"]
    assert "miễn phí" in out["models"][1]["desc"] and "128k" in out["models"][0]["desc"]


def test_live_result_is_cached_but_failures_are_not(db, monkeypatch):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, json=OR_LIST)

    setup_transport(monkeypatch, handler)
    run(model_catalog.list_models("openrouter"))
    run(model_catalog.list_models("openrouter"))
    assert calls["n"] == 1
    run(model_catalog.list_models("openrouter", refresh=True))
    assert calls["n"] == 2

    model_catalog._cache.clear()
    setup_transport(monkeypatch, lambda req: httpx.Response(503))
    assert run(model_catalog.list_models("openrouter"))["source"] == "fallback"
    assert not model_catalog._cache


def test_models_endpoint_validates_provider(db):
    from fastapi.testclient import TestClient
    from brain_app.main import app
    set_setting("embedding_provider", "hash")
    with TestClient(app) as c:
        assert c.get("/api/settings/models", params={"provider": "nope"}).status_code == 400
        assert c.get("/api/settings/models", params={"provider": "gemini"}).json()["source"] == "fallback"


def test_gemini_chat_uses_header_key_and_skips_thought_parts(db):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["hdr"] = req.headers.get("x-goog-api-key")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": "suy nghĩ nội bộ", "thought": True}, {"text": "Câu trả lời "}, {"text": "cuối cùng"}]}}]})

    rag_service._transport = httpx.MockTransport(handler)
    try:
        text = run(rag_service._call_gemini_rag(KEY, "gemini-3.8-flash", "q", "ctx"))
    finally:
        rag_service._transport = None
    assert text == "Câu trả lời cuối cùng"
    assert KEY not in seen["url"] and seen["hdr"] == KEY
