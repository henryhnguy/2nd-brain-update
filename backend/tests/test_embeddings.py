import asyncio
import json
import sys

import httpx
import numpy as np
import pytest

from brain_app import database
from brain_app.rag import embeddings
from brain_app.rag.embeddings import EmbeddingError, embedding_service, GEMINI_DIM
from brain_app.rag.rag_service import rag_service
from brain_app.rag.reindex import reindex_manager
from brain_app.rag.vector_store import vector_store
from tests.conftest import set_setting

KEY = "AIzaSy-test-key-1234567890"


def run(coro):
    return asyncio.run(coro)


def gemini_transport(handler):
    return httpx.MockTransport(handler)


def fake_vectors(n, dim=GEMINI_DIM, scale=3.0):
    return [{"values": [scale] * dim} for _ in range(n)]


# ----------------------------------------------------------------- provider resolution
def test_auto_without_key_is_weak_hash(db):
    st = embedding_service.status()
    assert st["resolved_provider"] == "hash"
    assert st["quality"] == "weak"
    assert "KHÔNG hiểu ngữ nghĩa" in st["warning"]


def test_auto_with_key_picks_gemini(db):
    set_setting("gemini_api_key", KEY)
    assert embedding_service.resolved_provider() == "gemini"
    assert embedding_service.active_tag() == f"gemini:gemini-embedding-001:{GEMINI_DIM}"


def test_explicit_local_never_auto_selected(db):
    set_setting("gemini_api_key", KEY)
    set_setting("embedding_provider", "local")
    assert embedding_service.resolved_provider() == "local"
    assert embedding_service.active_tag().startswith("local:")


def test_hash_is_deterministic_and_normalised(db):
    a = run(embedding_service.embed_query("quy trình kiểm tra AQL"))
    b = run(embedding_service.embed_query("quy trình kiểm tra AQL"))
    assert a == b
    assert abs(np.linalg.norm(a) - 1.0) < 1e-5


# ------------------------------------------------------------------------------ gemini
def test_gemini_batches_headers_and_task_types(db):
    set_setting("gemini_api_key", KEY)
    seen = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.append((req, body))
        return httpx.Response(200, json={"embeddings": fake_vectors(len(body["requests"]))})

    embedding_service._transport = gemini_transport(handler)
    vecs = run(embedding_service.embed_documents([f"đoạn {i}" for i in range(120)]))

    assert len(vecs) == 120
    assert [len(b["requests"]) for _, b in seen] == [50, 50, 20]
    req, body = seen[0]
    assert KEY not in str(req.url)                       # key never in URL
    assert req.headers["x-goog-api-key"] == KEY
    assert req.url.path.endswith("/models/gemini-embedding-001:batchEmbedContents")
    r0 = body["requests"][0]
    assert r0["taskType"] == "RETRIEVAL_DOCUMENT"
    assert r0["outputDimensionality"] == GEMINI_DIM
    assert abs(np.linalg.norm(vecs[0]) - 1.0) < 1e-5     # normalised


def test_gemini_query_uses_query_task(db):
    set_setting("gemini_api_key", KEY)
    tasks = []

    def handler(req):
        body = json.loads(req.content)
        tasks.append(body["requests"][0]["taskType"])
        return httpx.Response(200, json={"embeddings": fake_vectors(1)})

    embedding_service._transport = gemini_transport(handler)
    run(embedding_service.embed_query("câu hỏi"))
    assert tasks == ["RETRIEVAL_QUERY"]


def test_gemini_retries_429_then_succeeds(db):
    set_setting("gemini_api_key", KEY)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"error": {"message": "quota"}})
        return httpx.Response(200, json={"embeddings": fake_vectors(1)})

    embedding_service._transport = gemini_transport(handler)
    assert len(run(embedding_service.embed_documents(["x"]))) == 1
    assert calls["n"] == 3


def test_gemini_404_raises_instead_of_silent_fallback(db):
    """Regression: the old code swallowed this (text-embedding-004 retired) and used hash vectors."""
    set_setting("gemini_api_key", KEY)
    set_setting("embedding_gemini_model", "text-embedding-004")
    embedding_service._transport = gemini_transport(
        lambda req: httpx.Response(404, json={"error": {"message": "models/text-embedding-004 is not found"}}))
    with pytest.raises(EmbeddingError) as e:
        run(embedding_service.embed_query("hello"))
    msg = str(e.value)
    assert "404" in msg and "ngừng hỗ trợ" in msg and "not found" in msg


def test_gemini_drops_task_type_when_model_rejects_it(db):
    set_setting("gemini_api_key", KEY)
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if "taskType" in body["requests"][0]:
            return httpx.Response(400, json={"error": {"message": "taskType is not supported"}})
        return httpx.Response(200, json={"embeddings": fake_vectors(1)})

    embedding_service._transport = gemini_transport(handler)
    assert len(run(embedding_service.embed_documents(["x"]))) == 1
    assert "taskType" not in bodies[-1]["requests"][0]


def test_gemini_without_key_is_explicit_error(db):
    set_setting("embedding_provider", "gemini")
    with pytest.raises(EmbeddingError):
        run(embedding_service.embed_query("x"))


# -------------------------------------------------------------------------------- local
class FakeLocalModel:
    def __init__(self, dim):
        self.dim = dim
        self.inputs = []

    def embed(self, texts, batch_size=16):
        self.inputs.extend(texts)
        for i, _ in enumerate(texts):
            v = np.zeros(self.dim, dtype=np.float32)
            v[i % self.dim] = 5.0
            yield v


def test_local_e5_gets_query_and_passage_prefixes(db, monkeypatch):
    set_setting("embedding_provider", "local")
    fake = FakeLocalModel(1024)
    monkeypatch.setattr(embedding_service, "_load_local", lambda model_id: fake)
    run(embedding_service.embed_documents(["nội dung A", "nội dung B"]))
    run(embedding_service.embed_query("hỏi gì"))
    assert fake.inputs == ["passage: nội dung A", "passage: nội dung B", "query: hỏi gì"]


def test_local_minilm_has_no_prefix_and_vectors_normalised(db, monkeypatch):
    set_setting("embedding_provider", "local")
    set_setting("embedding_local_model", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    fake = FakeLocalModel(384)
    monkeypatch.setattr(embedding_service, "_load_local", lambda model_id: fake)
    vecs = run(embedding_service.embed_documents(["abc"]))
    assert fake.inputs == ["abc"]
    assert abs(np.linalg.norm(vecs[0]) - 1.0) < 1e-5


def test_local_without_fastembed_explains_how_to_install(db, monkeypatch):
    set_setting("embedding_provider", "local")
    monkeypatch.setitem(sys.modules, "fastembed", None)   # makes `import fastembed` fail
    with pytest.raises(EmbeddingError) as e:
        run(embedding_service.embed_query("x"))
    assert "pip install" in str(e.value)
    assert embedding_service.status()["local_available"] is False


# -------------------------------------------------------------- storage / reindex flow
def _chunk(tag, vec, title="t", idx=0, content="c"):
    return {"source_type": "note", "source_id": 1, "source_title": title, "chunk_index": idx,
            "content": content, "embedding": vec, "embedding_model": tag, "metadata": {},
            "created_at": "2026-01-01"}


def test_migration_adds_embedding_model_column(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL,
        source_id INTEGER NOT NULL, source_title TEXT NOT NULL, chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL, embedding TEXT NOT NULL, metadata TEXT DEFAULT '{}', created_at TEXT NOT NULL)""")
    c.execute("INSERT INTO chunks (source_type,source_id,source_title,chunk_index,content,embedding,created_at)"
              " VALUES ('note',1,'old',0,'legacy','[1,0]','x')")
    c.commit(); c.close()
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    conn = database.get_db_connection()
    row = conn.execute("SELECT embedding_model FROM chunks").fetchone()
    conn.close()
    assert row["embedding_model"] == ""          # legacy rows count as stale -> will be re-embedded


def test_search_only_compares_vectors_of_same_model(db):
    vector_store.add_chunks([
        _chunk("A", [1.0, 0.0], title="in-A"),
        _chunk("B", [1.0, 0.0], title="in-B"),
    ])
    res = vector_store.similarity_search([1.0, 0.0], model_tag="A", top_k=5)
    assert [r["source_title"] for r in res] == ["in-A"]
    assert vector_store.similarity_search([1.0, 0.0], model_tag="missing") == []


def test_failed_embedding_stores_pending_chunks_and_note_save_survives(db):
    set_setting("gemini_api_key", KEY)
    embedding_service._transport = gemini_transport(
        lambda req: httpx.Response(404, json={"error": {"message": "gone"}}))
    run(rag_service.index_note(1, "Quy trình QC", "Kiểm tra AQL 2.5 trước khi đóng hàng", "Areas", []))
    st = vector_store.stats(embedding_service.active_tag())
    assert st["total"] >= 1 and st["current"] == 0 and st["stale"] == st["total"]
    assert "gone" in rag_service.last_embedding_error


def test_answer_query_reports_error_when_nothing_to_fall_back_on(db):
    set_setting("gemini_api_key", KEY)
    embedding_service._transport = gemini_transport(
        lambda req: httpx.Response(403, json={"error": {"message": "blocked"}}))
    out = run(rag_service.answer_query("AQL là gì?"))
    assert "Không thể tìm kiếm" in out["answer"] and out["sources"] == []


def test_answer_query_falls_back_to_keywords_when_embedding_fails(db):
    set_setting("embedding_provider", "hash")
    run(rag_service.index_note(3, "Quy trình AQL", "Kiểm tra AQL 2.5 trước khi đóng hàng xuất khẩu", "Areas", []))
    set_setting("gemini_api_key", KEY)
    set_setting("embedding_provider", "gemini")
    embedding_service._transport = gemini_transport(
        lambda req: httpx.Response(403, json={"error": {"message": "blocked"}}))
    out = run(rag_service.answer_query("AQL là gì?"))
    assert "tìm theo **từ khóa**" in out["answer"] and "blocked" in out["answer"]
    assert out["sources"] and out["sources"][0]["match"] == "keyword"


def test_reindex_recovers_pending_and_stale_chunks(db):
    # 1) note saved while Gemini is broken -> pending
    set_setting("gemini_api_key", KEY)
    embedding_service._transport = gemini_transport(lambda req: httpx.Response(500, json={}))
    run(rag_service.index_note(7, "Bonding", "Kiểm tra độ bám dính keo bonding đế giày", "Areas", ["qc"]))
    assert vector_store.stats(embedding_service.active_tag())["current"] == 0

    # 2) user switches to hash provider -> reindex embeds everything under the new tag
    set_setting("embedding_provider", "hash")
    tag = embedding_service.active_tag()
    run(reindex_manager.run())
    assert reindex_manager.state["error"] is None
    assert reindex_manager.state["done"] == reindex_manager.state["total"] > 0
    assert vector_store.stats(tag)["stale"] == 0

    # 3) search now finds it
    out = run(rag_service.answer_query("độ bám dính keo bonding"))
    assert any("Bonding" in s["title"] for s in out["sources"])


def test_reindex_reports_error_when_provider_down(db):
    set_setting("embedding_provider", "hash")
    run(rag_service.index_note(1, "n", "nội dung ghi chú đủ dài để tạo chunk", "Areas", []))
    set_setting("embedding_provider", "gemini")
    set_setting("gemini_api_key", KEY)
    embedding_service._transport = gemini_transport(
        lambda req: httpx.Response(404, json={"error": {"message": "model gone"}}))
    run(reindex_manager.run())
    assert reindex_manager.state["running"] is False
    assert "model gone" in reindex_manager.state["error"]


def test_local_download_failure_is_cached_briefly(db, monkeypatch):
    """A failed download must not be retried on every request (fastembed retries for ~1 min)."""
    set_setting("embedding_provider", "local")
    attempts = {"n": 0}

    class BrokenTextEmbedding:
        def __init__(self, *a, **k):
            attempts["n"] += 1
            raise RuntimeError("offline")

    import types
    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=BrokenTextEmbedding))
    for _ in range(3):
        with pytest.raises(EmbeddingError) as e:
            run(embedding_service.embed_query("x"))
        assert "offline" in str(e.value)
    assert attempts["n"] == 1
    embedding_service._local_failures.clear()
