import asyncio

from brain_app import database
from brain_app.rag.embeddings import embedding_service
from brain_app.rag.rag_service import rag_service
from brain_app.rag.vector_store import build_fts_query, vector_store
from tests.conftest import set_setting
from tests.test_embeddings import _chunk


def run(c):
    return asyncio.run(c)


def test_fts_query_builder_is_safe_and_drops_stopwords():
    assert build_fts_query("") == ""
    q = build_fts_query('Quy trình "kiểm tra" AQL là gì?')
    assert '"quy"' in q and '"trình"*' in q and '"kiểm"*' in q and '"aql"' in q
    assert '"là"' not in q and '"gì"' not in q
    # injection-ish input never produces raw operators / unbalanced quotes
    nasty = build_fts_query('foo" OR NOT ( * ) bar')
    assert nasty.count('"') % 2 == 0 and "(" not in nasty and "*)" not in nasty


def test_fts_is_populated_and_kept_in_sync_by_triggers(db):
    vector_store.add_chunks([_chunk("A", [1.0, 0.0], title="Keo bonding", content="Độ bám dính keo bonding đế giày")])
    assert [r["source_title"] for r in vector_store.keyword_search("bonding")] == ["Keo bonding"]
    vector_store.delete_by_source("note", 1)
    assert vector_store.keyword_search("bonding") == []


def test_keyword_search_is_accent_insensitive_and_prefix_aware(db):
    vector_store.add_chunks([_chunk("A", [1.0, 0.0], title="QC", content="Kiểm tra hiện tượng ố vàng yellowing của đế giày")])
    assert vector_store.keyword_search("o vang")           # typed without accents
    assert vector_store.keyword_search("yellow")           # prefix of 'yellowing'
    assert vector_store.keyword_search("khong co tu nay xyz") == []


def test_migration_rebuilds_fts_for_existing_chunks(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL,
        source_id INTEGER NOT NULL, source_title TEXT NOT NULL, chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL, embedding TEXT NOT NULL, metadata TEXT DEFAULT '{}', created_at TEXT NOT NULL)""")
    c.execute("INSERT INTO chunks (source_type,source_id,source_title,chunk_index,content,embedding,created_at)"
              " VALUES ('note',1,'Cũ','0','Ghi chú cũ về bonding','[1,0]','x')")
    c.commit(); c.close()
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    assert [r["source_title"] for r in vector_store.keyword_search("bonding")] == ["Cũ"]


def test_hybrid_fuses_and_labels_sources(db):
    vector_store.add_chunks([
        _chunk("T", [1.0, 0.0], title="chỉ-ngữ-nghĩa", idx=0, content="nội dung không liên quan từ khóa"),
        _chunk("T", [0.0, 1.0], title="chỉ-từ-khóa", idx=1, content="quy trình kiểm tra bonding"),
        _chunk("T", [0.9, 0.1], title="cả-hai", idx=2, content="bonding và keo dán"),
    ])
    res = vector_store.hybrid_search("bonding", [1.0, 0.0], model_tag="T", top_k=5)
    by_title = {r["source_title"]: r for r in res}
    assert by_title["chỉ-ngữ-nghĩa"]["match"] == "semantic"
    assert by_title["chỉ-từ-khóa"]["match"] in ("keyword", "both")
    assert by_title["cả-hai"]["match"] == "both"
    assert res[0]["source_title"] == "cả-hai"            # appears in both rankings -> ranked first
    assert by_title["cả-hai"]["score"] > 0.9              # score stays the cosine similarity


def test_hybrid_without_vector_is_keyword_only(db):
    vector_store.add_chunks([_chunk("", [], title="k", content="ghi chú về bonding")])
    res = vector_store.hybrid_search("bonding", None, model_tag="T")
    assert len(res) == 1 and res[0]["match"] == "keyword" and res[0]["score"] == 0.0


def test_keyword_finds_chunks_even_when_embeddings_are_pending(db):
    """Chunks saved while embedding was down (no vector yet) are still searchable by keyword."""
    set_setting("embedding_provider", "gemini")   # no key -> embedding fails -> chunks pending
    run(rag_service.index_note(5, "Bonding", "Kiểm tra độ bám dính keo bonding", "Areas", []))
    assert vector_store.stats(embedding_service.active_tag())["current"] == 0
    res = vector_store.hybrid_search("bonding", None, model_tag=embedding_service.active_tag())
    assert res and res[0]["source_title"] == "Bonding"


def test_followup_questions_borrow_the_previous_user_question():
    hist = [{"role": "user", "content": "Quy trình kiểm tra AQL gồm những bước nào?"},
            {"role": "assistant", "content": "Gồm ba bước..."}]
    assert "AQL" in rag_service._retrieval_text("còn bước hai thì sao?", hist)
    long_q = "Hãy giải thích chi tiết toàn bộ quy trình kiểm tra chất lượng đế giày thể thao"
    assert rag_service._retrieval_text(long_q, hist) == long_q      # long questions stand alone
    assert rag_service._retrieval_text("còn gì nữa?", None) == "còn gì nữa?"


def test_local_synthesis_trusts_keyword_hits_even_with_zero_cosine(db):
    """Regression: keyword-only hits have score 0.0 and used to be reported as 'nothing found'."""
    chunks = [{"source_type": "note", "source_id": 1, "source_title": "Yellowing", "content": "ố vàng của đế giày",
               "score": 0.0, "match": "keyword", "chunk_index": 0, "metadata": {}}]
    assert "Không tìm thấy" not in rag_service._generate_local_synthesis("yellowing là gì?", chunks)
    weak = [dict(chunks[0], match="semantic", score=0.01)]
    assert "Không tìm thấy" in rag_service._generate_local_synthesis("yellowing là gì?", weak)
