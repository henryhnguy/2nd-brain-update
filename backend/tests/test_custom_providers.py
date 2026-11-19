import json

import httpx
import pytest
from fastapi.testclient import TestClient

from brain_app.main import app
from brain_app.rag import custom_providers, llm
from tests.conftest import set_setting


@pytest.fixture
def client(db, monkeypatch):
    async def no_seed_indexing():
        return None
    monkeypatch.setattr("brain_app.main._startup_indexing", no_seed_indexing)
    with TestClient(app) as c:
        yield c


def mock(handler, monkeypatch):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(custom_providers, "_transport", transport)
    monkeypatch.setattr(llm, "_transport", transport)


def make(client, **over):
    body = {"name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1/", "api_key": "nvapi-SECRET-123456",
            "models": ["meta/llama-3.3-70b-instruct", "meta/llama-3.3-70b-instruct"], "default_model": "deepseek-ai/deepseek-r1"}
    body.update(over)
    r = client.post("/api/settings/custom-providers", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_create_normalizes_url_dedupes_models_and_never_leaks_the_key(client):
    p = make(client, base_url="https://integrate.api.nvidia.com/v1/chat/completions/")
    assert p["id"] == "nvidia-nim" and p["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert p["models"] == ["deepseek-ai/deepseek-r1", "meta/llama-3.3-70b-instruct"]   # default_model được thêm vào đầu, không trùng
    assert p["has_key"] is True and "SECRET" not in json.dumps(p)
    for url in ("/api/settings/custom-providers", "/api/settings"):
        assert "SECRET" not in client.get(url).text                                     # không endpoint nào trả key
    assert client.get("/api/settings").json()["custom_providers"][0]["id"] == "nvidia-nim"


def test_validation(client):
    assert client.post("/api/settings/custom-providers", json={"name": "X", "base_url": "ftp://x", "models": ["m"]}).status_code == 400
    assert client.post("/api/settings/custom-providers", json={"name": "X", "base_url": "http://localhost:11434/v1"}).status_code == 400  # thiếu model
    assert client.post("/api/settings/custom-providers", json={"name": "", "base_url": "http://x/v1", "models": ["m"]}).status_code == 400
    make(client)
    assert client.post("/api/settings/custom-providers", json={"name": "nvidia nim", "base_url": "http://x/v1", "models": ["m"]}).status_code == 409
    assert client.post("/api/settings/custom-providers", json={"id": "nope", "name": "Y", "base_url": "http://x/v1", "models": ["m"]}).status_code == 404


def test_update_keeps_key_unless_told_otherwise(client):
    make(client)
    r = client.post("/api/settings/custom-providers", json={"id": "nvidia-nim", "name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1", "models": ["a"]})
    assert r.json()["has_key"] is True and r.json()["models"] == ["a"]                   # api_key vắng mặt = giữ nguyên
    r = client.post("/api/settings/custom-providers", json={"id": "nvidia-nim", "name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1", "models": ["a"], "api_key": ""})
    assert r.json()["has_key"] is False                                                   # chuỗi rỗng = xoá key


def test_models_endpoint_merges_live_list_and_falls_back(client, monkeypatch):
    make(client)
    mock(lambda req: httpx.Response(200, json={"data": [{"id": "meta/llama-3.3-70b-instruct"}, {"id": "mistralai/mixtral"}]}), monkeypatch)
    r = client.get("/api/settings/models", params={"provider": "custom:nvidia-nim"}).json()
    assert r["source"] == "live" and [m["id"] for m in r["models"]] == ["deepseek-ai/deepseek-r1", "meta/llama-3.3-70b-instruct", "mistralai/mixtral"]
    mock(lambda req: httpx.Response(404, json={"error": "no"}), monkeypatch)
    r = client.get("/api/settings/models", params={"provider": "custom:nvidia-nim", "refresh": "true"}).json()
    assert r["source"] == "configured" and len(r["models"]) == 2 and r["error"]
    assert client.get("/api/settings/models", params={"provider": "custom:missing"}).status_code == 400


def test_connection_test_reports_success_and_helpful_errors(client, monkeypatch):
    make(client)
    seen = {}

    def ok(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers.get("authorization"), json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    mock(ok, monkeypatch)
    r = client.post("/api/settings/custom-providers/nvidia-nim/test").json()
    assert r["ok"] is True and r["reply"] == "OK" and r["model"] == "deepseek-ai/deepseek-r1"
    assert seen["url"] == "https://integrate.api.nvidia.com/v1/chat/completions" and seen["auth"] == "Bearer nvapi-SECRET-123456"
    mock(lambda req: httpx.Response(401, json={"error": {"message": "bad key"}}), monkeypatch)
    r = client.post("/api/settings/custom-providers/nvidia-nim/test").json()
    assert r["ok"] is False and "bad key" in r["error"] and "API key" in r["error"]

    def boom(req):
        raise httpx.ConnectError("refused")
    mock(boom, monkeypatch)
    assert client.post("/api/settings/custom-providers/nvidia-nim/test").json()["ok"] is False
    assert client.post("/api/settings/custom-providers/none/test").status_code == 404


def test_llm_client_uses_the_selected_custom_provider(client, monkeypatch):
    import asyncio
    make(client, name="Ollama", base_url="http://localhost:11434/v1", api_key="", models=["llama3.1"], default_model="llama3.1")
    assert client.post("/api/settings", json={"llm_provider": "custom:ollama"}).status_code == 200
    assert llm.is_configured()                                                            # key trống vẫn dùng được (chạy trên máy)
    seen = {}

    def handler(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers.get("authorization"), json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}]})
    mock(handler, monkeypatch)
    assert asyncio.run(llm.complete_json("sys", "usr")) == {"a": 1}
    assert seen["url"] == "http://localhost:11434/v1/chat/completions" and seen["auth"] is None
    assert seen["body"]["model"] == "llama3.1" and seen["body"]["response_format"] == {"type": "json_object"}
    client.post("/api/settings/custom-providers", json={"id": "ollama", "name": "Ollama", "base_url": "http://localhost:11434/v1", "models": ["llama3.1"], "json_mode": "off"})
    asyncio.run(llm.complete_json("sys", "usr"))
    assert "response_format" not in seen["body"]                                         # json_mode=off: không gửi response_format
    mock(lambda req: httpx.Response(500, json={"error": {"message": "boom"}}), monkeypatch)
    monkeypatch.setattr(llm, "_sleep", lambda s: asyncio.sleep(0))
    with pytest.raises(llm.LLMError, match="Ollama lỗi 500"):
        asyncio.run(llm.complete("s", "u"))


def test_selecting_and_deleting_the_default_provider(client):
    make(client)
    assert client.post("/api/settings", json={"llm_provider": "custom:ghost"}).status_code == 400
    assert client.post("/api/settings", json={"llm_provider": "banana"}).status_code == 400
    client.post("/api/settings", json={"llm_provider": "custom:nvidia-nim"})
    assert client.get("/api/settings").json()["llm_provider"] == "custom:nvidia-nim"
    assert client.delete("/api/settings/custom-providers/nvidia-nim").status_code == 200
    assert client.get("/api/settings").json()["llm_provider"] == "gemini"                # xoá provider mặc định -> về Gemini
    assert client.delete("/api/settings/custom-providers/nvidia-nim").status_code == 404


def test_chat_routes_to_the_custom_provider(client, monkeypatch):
    from brain_app.rag.rag_service import rag_service
    make(client)
    seen = {}

    async def fake(self, key, model, question, context, history, **kw):
        seen.update(key=key, model=model, **kw)
        return "trả lời từ custom"
    monkeypatch.setattr(type(rag_service), "_call_openrouter_rag", fake)
    r = client.post("/api/chat/query", json={"question": "Xin chào", "provider": "custom:nvidia-nim", "model": "meta/llama-3.3-70b-instruct"})
    assert r.status_code == 200 and "trả lời từ custom" in r.text
    assert seen["model"] == "meta/llama-3.3-70b-instruct" and seen["label"] == "NVIDIA NIM"
    assert seen["url"] == "https://integrate.api.nvidia.com/v1/chat/completions" and seen["headers"]["Authorization"].startswith("Bearer nvapi")
    client.delete("/api/settings/custom-providers/nvidia-nim")
    r = client.post("/api/chat/query", json={"question": "Xin chào", "provider": "custom:nvidia-nim"})
    assert "không còn tồn tại" in r.text                                                  # provider đã xoá: báo rõ, không lỗi 500
