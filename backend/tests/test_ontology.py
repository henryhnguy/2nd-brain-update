import pytest
from fastapi.testclient import TestClient

from brain_app import database
from brain_app.main import app
from brain_app.ontology import store
from tests.conftest import set_setting


@pytest.fixture
def client(db, monkeypatch):
    set_setting("embedding_provider", "hash")

    async def no_seed_indexing():   # không lập chỉ mục ghi chú chào mừng có sẵn: kết quả chỉ gồm dữ liệu của test
        return None
    monkeypatch.setattr("brain_app.main._startup_indexing", no_seed_indexing)
    with TestClient(app) as c:
        yield c


def add_chunk(source_type, source_id, title, content, idx=0):
    conn = database.get_db_connection()
    conn.execute(
        "INSERT INTO chunks (source_type, source_id, source_title, chunk_index, content, embedding, embedding_model, metadata, created_at) "
        "VALUES (?, ?, ?, ?, ?, '[]', '', '{}', '2026-11-18')", (source_type, source_id, title, idx, content))
    conn.commit()
    conn.close()


def make_term(client, name, definition="", aliases=None, kind="concept"):
    r = client.post("/api/ontology/terms", json={"name": name, "kind": kind, "definition": definition, "aliases": aliases or []})
    assert r.status_code == 200, r.text
    return r.json()


def test_create_defaults_to_draft_and_names_are_unique_ignoring_accents(client):
    t = make_term(client, "Độ vàng", aliases=["Yellowing"])
    assert t["status"] == "draft" and t["aliases"] == ["Yellowing"]
    assert client.post("/api/ontology/terms", json={"name": "do vang"}).status_code == 409
    assert client.post("/api/ontology/terms", json={"name": "Màu ố", "aliases": ["yellowing"]}).status_code == 409
    assert client.post("/api/ontology/terms", json={"name": "X", "kind": "bogus"}).status_code == 400


def test_approve_requires_definition(client):
    t = make_term(client, "AQL")
    assert client.post(f"/api/ontology/terms/{t['id']}/approve").status_code == 400
    client.patch(f"/api/ontology/terms/{t['id']}", json={"definition": "Acceptable Quality Limit: mức lỗi tối đa chấp nhận."})
    r = client.post(f"/api/ontology/terms/{t['id']}/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approved_at"]
    # đã duyệt thì không được xoá trống định nghĩa
    assert client.patch(f"/api/ontology/terms/{t['id']}", json={"definition": ""}).status_code == 400


def test_only_approved_terms_affect_matching_expansion_and_glossary(client):
    t = make_term(client, "AQL", "Acceptable Quality Limit: mức lỗi tối đa chấp nhận khi lấy mẫu.", ["mức lấy mẫu"])
    assert store.match_terms("kiểm tra theo AQL 2.5") == []          # nháp: không có tác dụng
    assert store.expand_query("AQL là gì") == "AQL là gì"
    assert store.glossary_block("AQL là gì") == ""
    client.post(f"/api/ontology/terms/{t['id']}/approve")
    assert [m["name"] for m in store.match_terms("Kiểm tra theo aql 2.5")] == ["AQL"]
    assert [m["name"] for m in store.match_terms("quy định về MUC LAY MAU")] == ["AQL"]  # alias, không dấu
    assert store.match_terms("AQLX hay XAQL") == []                    # ranh giới từ
    expanded = store.expand_query("AQL là gì")
    assert "muc" in expanded and "lay" in expanded and "mau" in expanded
    g = store.glossary_block("AQL là gì")
    assert "**AQL**" in g and "mức lỗi tối đa" in g
    client.post(f"/api/ontology/terms/{t['id']}/unapprove")
    assert store.match_terms("AQL") == []


def test_search_uses_aliases_of_approved_terms(client):
    add_chunk("document", 1, "SOP lấy mẫu", "Quy định mức lấy mẫu 2.5 cho lỗi major trước khi xuất hàng.")
    add_chunk("document", 2, "Khác", "Tài liệu về keo dán đế giày.")
    t = make_term(client, "AQL", "Acceptable Quality Limit: mức lỗi tối đa chấp nhận.", ["mức lấy mẫu"])
    titles = lambda: [r["source_title"] for r in client.get("/api/search", params={"q": "AQL"}).json()]
    assert titles() == []                                              # chưa duyệt: "AQL" không có trong văn bản
    client.post(f"/api/ontology/terms/{t['id']}/approve")
    r = client.get("/api/search", params={"q": "AQL"})
    assert [x["source_title"] for x in r.json()] == ["SOP lấy mẫu"]
    assert "X-Search-Expanded" in r.headers


def test_evidence_is_verified_against_the_real_source(client):
    add_chunk("document", 5, "QMS", "Bonding gap là khe hở giữa đế và upper sau khi dán. Phải sửa trước khi đóng gói.")
    t = make_term(client, "Bonding gap")
    ok = client.post(f"/api/ontology/terms/{t['id']}/evidence",
                     json={"source_type": "document", "source_id": 5, "quote": "Bonding gap là khe hở giữa đế và upper"})
    assert ok.json()["verified"] is True
    fake = client.post(f"/api/ontology/terms/{t['id']}/evidence",
                       json={"source_type": "document", "source_id": 5, "quote": "Bonding gap là mức nhiệt tối đa của máy ép"})
    assert fake.json()["verified"] is False                            # câu bịa không được đánh dấu đã kiểm
    assert client.post(f"/api/ontology/terms/{t['id']}/evidence",
                       json={"source_type": "document", "source_id": 99, "quote": "không có nguồn này"}).status_code == 404
    full = client.get(f"/api/ontology/terms/{t['id']}").json()
    assert [e["verified"] for e in full["evidence"]] == [1, 0]
    assert client.get("/api/ontology/terms").json()[0]["verified_evidence"] == 1


def test_relations_and_cascade_delete(client):
    a, b = make_term(client, "Bonding gap"), make_term(client, "Over cement")
    r = client.post("/api/ontology/relations", json={"from_id": a["id"], "to_id": b["id"], "kind": "related_to"})
    assert r.status_code == 200
    assert client.post("/api/ontology/relations", json={"from_id": a["id"], "to_id": b["id"], "kind": "related_to"}).status_code == 409
    assert client.post("/api/ontology/relations", json={"from_id": a["id"], "to_id": a["id"], "kind": "is_a"}).status_code == 400
    assert client.post("/api/ontology/relations", json={"from_id": a["id"], "to_id": b["id"], "kind": "nope"}).status_code == 400
    assert client.get(f"/api/ontology/terms/{b['id']}").json()["relations"][0]["direction"] == "in"
    client.delete(f"/api/ontology/terms/{a['id']}")
    assert client.get("/api/ontology/graph").json()["edges"] == []


def test_glossary_includes_relations_to_approved_neighbours_only(client):
    a = make_term(client, "Bonding gap", "Khe hở giữa đế và upper sau khi dán keo.")
    b = make_term(client, "Over cement", "Keo tràn ra ngoài đường dán.")
    client.post("/api/ontology/relations", json={"from_id": a["id"], "to_id": b["id"], "kind": "related_to"})
    client.post(f"/api/ontology/terms/{a['id']}/approve")
    assert "Over cement" not in store.glossary_block("bonding gap")    # láng giềng còn nháp
    client.post(f"/api/ontology/terms/{b['id']}/approve")
    assert "related_to → Over cement" in store.glossary_block("bonding gap")


def test_suggest_finds_repeated_codes_with_verbatim_quotes_and_accept_creates_drafts(client):
    add_chunk("document", 1, "SOP A", "Theo QMS-FTW.06 phải kiểm tra bonding gap. Mức AQL 2.5 áp dụng cho hàng loại major.")
    add_chunk("document", 2, "SOP B", "Báo cáo dùng AQL để quyết định đạt hay không. Xem QMS-FTW.06 để biết thêm.")
    add_chunk("document", 3, "SOP C", "Chỉ nhắc XYZ một lần duy nhất.")
    cands = client.post("/api/ontology/suggest", json={}).json()
    names = [c["name"] for c in cands]
    assert "AQL" in names and "QMS-FTW.06" in names and "XYZ" not in names
    for c in cands:
        assert c["sources"] >= 2
        chunks = [{"content": "Theo QMS-FTW.06 phải kiểm tra bonding gap. Mức AQL 2.5 áp dụng cho hàng loại major."},
                  {"content": "Báo cáo dùng AQL để quyết định đạt hay không. Xem QMS-FTW.06 để biết thêm."}]
        assert store.verify_quote(c["quote"], chunks)
    res = client.post("/api/ontology/suggest/accept", json={"candidates": cands}).json()
    assert res["created"] == len(cands)
    terms = client.get("/api/ontology/terms", params={"status": "draft"}).json()
    assert {t["name"] for t in terms} >= {"AQL", "QMS-FTW.06"} and all(t["verified_evidence"] == 1 for t in terms)
    assert client.post("/api/ontology/suggest", json={}).json() == []  # đã là thuật ngữ nên không gợi ý lại


def test_export_import_roundtrip_imports_as_draft(client):
    a = make_term(client, "Bonding gap", "Khe hở giữa đế và upper.", ["BG"])
    b = make_term(client, "Over cement", "Keo tràn ra ngoài.")
    client.post("/api/ontology/relations", json={"from_id": a["id"], "to_id": b["id"], "kind": "related_to"})
    client.post(f"/api/ontology/terms/{a['id']}/approve")
    data = client.get("/api/ontology/export").json()
    md = client.get("/api/ontology/export", params={"format": "md"}).text
    assert "## Bonding gap" in md and "Over cement" in md.split("## Bonding gap")[1]
    for t in client.get("/api/ontology/terms").json():
        client.delete(f"/api/ontology/terms/{t['id']}")
    res = client.post("/api/ontology/import", json=data).json()
    assert res == {"created": 2, "skipped": 0, "relations": 1}
    assert all(t["status"] == "draft" for t in client.get("/api/ontology/terms").json())
    assert client.post("/api/ontology/import", json={"format": "x"}).status_code == 400


def test_chat_context_gets_the_glossary(client, monkeypatch):
    from brain_app.rag.rag_service import rag_service
    add_chunk("document", 1, "SOP", "Mức lấy mẫu 2.5 cho lỗi major.")
    t = make_term(client, "AQL", "Acceptable Quality Limit: mức lỗi tối đa chấp nhận.", ["mức lấy mẫu"])
    client.post(f"/api/ontology/terms/{t['id']}/approve")
    seen = {}

    async def fake_gemini(self, key, model, question, context, history):
        seen["context"] = context
        return "ok"
    monkeypatch.setattr(type(rag_service), "_call_gemini_rag", fake_gemini)
    set_setting("gemini_api_key", "x" * 20)
    r = client.post("/api/chat/query", json={"question": "AQL là gì?"})
    assert r.status_code == 200
    assert "Thuật ngữ đã duyệt" in seen["context"] and "**AQL**" in seen["context"]
    assert "Mức lấy mẫu 2.5" in seen["context"]                         # đoạn tìm được nhờ tên gọi khác
