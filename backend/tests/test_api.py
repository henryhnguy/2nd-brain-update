import pytest
from fastapi.testclient import TestClient

from brain_app.main import app
from tests.conftest import set_setting


@pytest.fixture
def client(db):
    set_setting("embedding_provider", "hash")   # keep API tests offline
    with TestClient(app) as c:
        yield c


def test_settings_expose_embedding_block(client):
    data = client.get("/api/settings").json()
    emb = data["embedding"]
    assert emb["resolved_provider"] == "hash"
    assert emb["quality"] == "weak"
    assert {m["id"] for m in emb["local_models"]} >= {"intfloat/multilingual-e5-large"}
    assert "chunks" in emb and "reindex" in emb


def test_switching_provider_changes_tag_and_validates_input(client):
    r = client.post("/api/settings", json={"embedding_provider": "bogus"})
    assert r.status_code == 400
    r = client.post("/api/settings", json={"embedding_local_model": "not/a-model"})
    assert r.status_code == 400
    r = client.post("/api/settings", json={"embedding_provider": "local",
                                           "embedding_local_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"})
    assert r.status_code == 200
    emb = client.get("/api/settings/embedding/status").json()
    assert emb["active_tag"] == "local:sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def test_embedding_test_endpoint_reports_ok_and_failure(client):
    ok = client.post("/api/settings/embedding/test").json()
    assert ok["ok"] and ok["dim"] == 384
    client.post("/api/settings", json={"embedding_provider": "gemini"})   # no key configured
    bad = client.post("/api/settings/embedding/test").json()
    assert bad["ok"] is False and "API Key" in bad["error"]


def test_search_degrades_to_keywords_with_warning_when_provider_unavailable(client):
    from urllib.parse import unquote
    client.post("/api/notes", json={"title": "Quy trình AQL", "content": "Kiểm tra AQL 2.5 trước khi đóng hàng xuất khẩu",
                                    "category": "Areas", "tags": []})
    client.post("/api/settings", json={"embedding_provider": "gemini"})   # no key configured
    r = client.get("/api/search", params={"q": "AQL"})
    assert r.status_code == 200
    assert "API Key" in unquote(r.headers["X-Search-Warning"])
    hits = r.json()
    assert hits and hits[0]["match"] == "keyword" and "AQL" in hits[0]["source_title"]


def test_note_search_and_manual_reindex_roundtrip(client):
    r = client.post("/api/notes", json={"title": "Yellowing", "content": "Kiểm tra hiện tượng ố vàng của đế giày trắng",
                                        "category": "Areas", "tags": ["qc"]})
    assert r.status_code in (200, 201)
    res = client.get("/api/search", params={"q": "ố vàng đế giày"}).json()
    assert any("Yellowing" in x["source_title"] for x in res)
    r = client.post("/api/settings/embedding/reindex", params={"all": "true"})
    assert r.status_code == 200 and "reindex" in r.json()
