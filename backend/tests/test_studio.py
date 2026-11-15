import asyncio
import json
import re

import httpx
import pytest

from brain_app.database import get_db_connection
from brain_app.rag import llm
from brain_app.rag.rag_service import rag_service
from brain_app.studio import engine, quality, store
from brain_app.studio.engine import StudioError
from brain_app.studio.jobs import write_jobs
from tests.conftest import set_setting


def run(c):
    return asyncio.run(c)


def seed_note(title, content, category="Areas", tags=None):
    conn = get_db_connection()
    cur = conn.execute("INSERT INTO notes (title, content, category, tags, pinned, created_at, updated_at) "
                       "VALUES (?,?,?,?,0,'x','x')", (title, content, category, json.dumps(tags or [])))
    nid = cur.lastrowid
    conn.commit()
    conn.close()
    run(rag_service.index_note(nid, title, content, category, tags or []))
    return nid


class FakeLLM:
    """Stands in for the real model; answers depend on the prompt's task description."""
    def __init__(self):
        self.calls = []
        self.prompts = []   # full (system, user) text
        self.fail_sections = set()
        self.sop_procedure_table = True
        self.uncited_paragraph = False

    @staticmethod
    def first_n(user):
        m = re.search(r"^\[(\d+)\]", user.split("NGUỒN:")[-1], re.MULTILINE)
        return int(m.group(1)) if m else 1

    async def __call__(self, system, user, **kw):
        self.calls.append((system[:60], user[:80]))
        self.prompts.append((system, user))
        if "DÀN Ý bài học" in system:
            return json.dumps({"sections": [{"title": "Mục tiêu học tập", "brief": "b"}, {"title": "Nội dung chính", "brief": "b"},
                                            {"title": "Bài tập", "brief": "b"}]})
        if "CÒN THIẾU" in system:
            return json.dumps({"questions": [{"question": "Ai phê duyệt?", "why": "cần người chịu trách nhiệm"},
                                             {"question": "Ngưỡng AQL?", "why": "cần ngưỡng"}]})
        if "NỘI DUNG cho đúng một mục của bài học" in system:
            title = re.search(r"MỤC CẦN VIẾT: (.+)", user).group(1).strip()
            if title in self.fail_sections:
                raise llm.LLMError("quota hết")
            body = f"Đây là phần giải thích đủ dài để được kiểm tra trích dẫn một cách đầy đủ và rõ ràng [{self.first_n(user)}]."
            if self.uncited_paragraph:
                body += "\n\nĐoạn này nói nhiều điều quan trọng nhưng không hề có trích dẫn nguồn nào cả, đủ dài để bị đánh dấu."
            return "## " + title + "\n" + body
        if "NỘI DUNG cho đúng một mục của SOP" in system:
            title = re.search(r"MỤC CẦN VIẾT: (.+)", user).group(1).strip()
            if title == "Quy trình thực hiện":
                return ("| Bước | Hoạt động | Người thực hiện | Tiêu chí đạt |\n|---|---|---|---|\n| 1 | Lấy mẫu | QA | Đủ số lượng |"
                        if self.sop_procedure_table else "Thực hiện các bước theo thứ tự.")
            if title == "Trách nhiệm":
                return "⚠️ [CẦN BỔ SUNG: người phê duyệt]"
            return f"Nội dung mục {title}."
        if "rà soát một bản SOP" in system:
            return json.dumps({"findings": [{"severity": "high", "section": "Quy trình thực hiện",
                                             "issue": "Bước 1 mơ hồ", "suggestion": "Nêu số lượng mẫu"}]})
        if "Tóm tắt một nguồn" in system:
            return "- ý chính 1\n- ý chính 2"
        if "DÀN Ý tài liệu tổng hợp" in system:
            ns = [int(x) for x in re.findall(r"^\[(\d+)\]", user, re.MULTILINE)]
            return ("Đây là dàn ý:\n```json\n" + json.dumps({"sections": [
                {"title": "Tổng quan", "brief": "b", "sources": ns[:2] + [99]},
                {"title": "Kết luận", "brief": "b", "sources": []}]}) + "\n```")
        if "NỘI DUNG cho đúng một mục của tài liệu tổng hợp" in system:
            ns = re.findall(r"^\[(\d+)\] Tóm tắt", user, re.MULTILINE)
            n = ns[0] if ns else "1"
            return f"Đoạn tổng hợp đủ dài để được kiểm tra, có dẫn nguồn rõ ràng và đầy đủ ý nghĩa [{n}] và thêm một số liệu không có thật [9]."
        raise AssertionError("prompt không nhận diện được: " + system[:80])


@pytest.fixture
def fake(db, monkeypatch):
    set_setting("embedding_provider", "hash")
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete", f)
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    return f


def new_doc(kind, params, scope=None):
    return store.create(kind, params.get("topic") or params.get("process_name"), params, scope or {})


# ------------------------------------------------------------------------ lesson
def test_lesson_flow_with_citations_and_sources(fake):
    seed_note("Keo bonding", "Độ bám dính keo bonding được kiểm tra bằng lực bóc 24 giờ sau khi dán đế.")
    doc = new_doc("lesson", {"topic": "độ bám dính keo bonding", "audience": "QA mới", "duration_min": 45})
    run(engine.make_outline(doc["id"]))
    d = store.get(doc["id"])
    assert [o["id"] for o in d["outline"]] == ["s1", "s2", "s3"] and d["status"] == "outline"
    for o in d["outline"]:
        run(engine.write_section(doc["id"], o["id"]))
    d = store.get(doc["id"])
    assert d["status"] == "written" and d["quality"]["coverage"] == 1.0 and not d["quality"]["invalid_citations"]
    md = engine.assemble(d)
    assert md.startswith("# độ bám dính keo bonding") and "**Đối tượng:** QA mới" in md and "45 phút" in md
    assert md.count("## Mục tiêu học tập") == 1          # model's own heading was stripped, ours added once
    assert "## Nguồn tham khảo" in md and "1. Keo bonding (ghi chú)" in md


def test_uncited_paragraphs_are_flagged(fake):
    seed_note("Keo", "Nội dung keo bonding đế giày dùng cho kiểm tra.")
    fake.uncited_paragraph = True
    doc = new_doc("lesson", {"topic": "keo bonding"})
    run(engine.make_outline(doc["id"]))
    for o in store.get(doc["id"])["outline"]:
        run(engine.write_section(doc["id"], o["id"]))
    q = store.get(doc["id"])["quality"]
    assert q["coverage"] < 1.0 and q["uncited_paragraphs"] and "không hề có trích dẫn" in q["uncited_paragraphs"][0]["excerpt"]


def test_scope_limits_retrieval_to_chosen_categories(fake):
    seed_note("Ghi chú Areas", "Quy trình kiểm tra keo bonding trong khu vực sản xuất.", category="Areas")
    seed_note("Ghi chú Archive", "Quy trình kiểm tra keo bonding cũ đã lưu trữ.", category="Archives")
    doc = new_doc("lesson", {"topic": "kiểm tra keo bonding"}, scope={"categories": ["Areas"]})
    run(engine.make_outline(doc["id"]))
    titles = {s["title"] for s in store.get(doc["id"])["sources"]}
    assert titles == {"Ghi chú Areas"}


def test_empty_scope_match_returns_nothing(fake):
    seed_note("N", "keo bonding", category="Areas")
    assert engine.resolve_scope({"categories": ["Khong-ton-tai"]}) == set()
    doc = new_doc("synthesis", {"topic": "keo bonding"}, scope={"categories": ["Khong-ton-tai"]})
    with pytest.raises(StudioError) as e:
        run(engine.make_outline(doc["id"]))
    assert e.value.status_code == 422


def test_studio_requires_llm_key(db, monkeypatch):
    set_setting("embedding_provider", "hash")
    monkeypatch.setattr(llm, "is_configured", lambda: False)
    doc = new_doc("lesson", {"topic": "x"})
    with pytest.raises(StudioError) as e:
        run(engine.make_outline(doc["id"]))
    assert "API key" in str(e.value) and e.value.status_code == 400


# --------------------------------------------------------------------------- sop
def test_sop_flow_questions_template_review_and_versions(fake):
    seed_note("AQL", "Kiểm tra AQL 2.5 mức II trước khi đóng hàng xuất khẩu.")
    doc = new_doc("sop", {"process_name": "Kiểm tra AQL", "department": "QC", "standards": "AQL 2.5"})
    run(engine.make_questions(doc["id"]))
    d = store.get(doc["id"])
    assert [q["id"] for q in d["questions"]] == ["q1", "q2"] and d["status"] == "questions"

    before = len(fake.calls)
    run(engine.make_outline(doc["id"]))
    assert len(fake.calls) == before                    # fixed template: no LLM call needed
    d = store.get(doc["id"])
    assert len(d["outline"]) == 9 and d["outline"][5]["title"] == "Quy trình thực hiện"

    store.mutate(doc["id"], lambda x: x["questions"][0].__setitem__("answer", "Quản lý QC"))
    for o in d["outline"]:
        run(engine.write_section(doc["id"], o["id"]))
    # the user's answer, and retrieved sources, reach every SOP section prompt
    sop_prompts = [u for sysm, u in fake.prompts if "mục của SOP" in sysm]
    assert len(sop_prompts) == 9
    assert all("Ai phê duyệt? → Quản lý QC" in u for u in sop_prompts)
    assert any("[1] AQL (Ghi chú)" in u for u in sop_prompts)

    run(engine.review(doc["id"]))
    d = store.get(doc["id"])
    kinds = {(f["kind"], f["section"]) for f in d["review"]}
    assert ("placeholder", "Trách nhiệm") in kinds
    assert ("unanswered", "Câu hỏi bổ sung") in kinds
    assert any(f["kind"] == "ai" for f in d["review"])
    assert d["review"][0]["severity"] == "high"          # sorted by severity
    assert not any(f["kind"] == "no_table" for f in d["review"])


def test_sop_review_flags_missing_procedure_table(fake):
    fake.sop_procedure_table = False
    doc = new_doc("sop", {"process_name": "Quy trình X"})
    run(engine.make_outline(doc["id"]))
    for o in store.get(doc["id"])["outline"]:
        run(engine.write_section(doc["id"], o["id"]))
    run(engine.review(doc["id"]))
    assert any(f["kind"] == "no_table" for f in store.get(doc["id"])["review"])


def test_sop_unwritten_sections_are_high_severity():
    doc = {"outline": [{"id": "s1", "title": "Mục đích"}], "sections": {"s1": {"status": "pending", "content": ""}},
           "questions": []}
    assert quality.sop_checks(doc, "Quy trình thực hiện")[0]["kind"] == "missing"


def test_versions_and_revision_history(fake):
    from fastapi.testclient import TestClient
    from brain_app.main import app
    with TestClient(app) as c:
        did = c.post("/api/studio/docs", json={"kind": "sop", "params": {"process_name": "SOP A", "department": "QC"}}).json()["id"]
        c.post(f"/api/studio/docs/{did}/outline")
        c.patch(f"/api/studio/docs/{did}", json={"sections": {"s1": "Mục đích rõ ràng."}})
        v1 = c.post(f"/api/studio/docs/{did}/versions", json={"label": "Bản đầu"}).json()
        assert v1["version"] == "1.0" and "| 1.0 |" in v1["markdown"]
        v2 = c.post(f"/api/studio/docs/{did}/versions", json={"label": "Sửa mục 1"}).json()
        assert v2["version"] == "1.1"
        v3 = c.post(f"/api/studio/docs/{did}/versions", json={"label": "Thay đổi lớn", "bump": "major"}).json()
        assert v3["version"] == "2.0"
        assert "## Lịch sử sửa đổi" in v3["markdown"] and "Bản đầu" in v3["markdown"] and "Thay đổi lớn" in v3["markdown"]
        old = c.get(f"/api/studio/docs/{did}/versions/1.0").json()
        assert "Lịch sử sửa đổi" in old["markdown"] and "Thay đổi lớn" not in old["markdown"]   # snapshot is frozen
        assert c.get(f"/api/studio/docs/{did}/versions/9.9").status_code == 404


# --------------------------------------------------------------------- synthesis
def test_synthesis_pipeline_summaries_outline_and_citation_check(fake):
    for i in range(3):
        seed_note(f"Nguồn {i}", f"Thông tin số {i} về lỗi đế cupsole và cách phòng ngừa bong keo ở đế giày.")
    doc = new_doc("synthesis", {"topic": "lỗi đế cupsole phòng ngừa", "length": "Ngắn"})
    run(engine.make_outline(doc["id"]))
    d = store.get(doc["id"])
    n_src = len(d["sources"])
    assert n_src == 3 and len(d["summaries"]) == 3
    assert sum("Tóm tắt một nguồn" in s for s, _ in fake.calls) == 3        # one summary call per source
    # fenced JSON with prose parsed; invalid source 99 dropped; empty sources -> all sources
    assert d["outline"][0]["sources"] and 99 not in d["outline"][0]["sources"]
    assert d["outline"][1]["sources"] == [1, 2, 3]

    for o in d["outline"]:
        run(engine.write_section(doc["id"], o["id"]))
    d = store.get(doc["id"])
    assert d["status"] == "written"
    assert d["quality"]["invalid_citations"] == [9]                         # [9] is not a real source
    assert "## Nguồn tham khảo" in engine.assemble(d)


def test_check_citations_ignores_headings_tables_and_short_lines():
    doc = {"sources": [{"n": 1}], "outline": [{"id": "s1", "title": "T"}],
           "sections": {"s1": {"content": "### Tiêu đề\n\n| a | b |\n|---|---|\n\nNgắn.\n\n"
                                          "Một đoạn dài hơn tám mươi ký tự nhưng chưa có dẫn nguồn nào hết, để kiểm tra việc đánh dấu.\n\n"
                                          "Đoạn có dẫn nguồn hợp lệ và cũng đủ dài để được tính là đoạn có trích dẫn [1, 2]."}}}
    q = quality.check_citations(doc)
    assert q["total_paragraphs"] == 2 and q["cited_paragraphs"] == 1 and q["invalid_citations"] == [2]


# --------------------------------------------------------------------- jobs
def test_write_job_survives_a_failing_section_and_reports_it(fake):
    seed_note("Keo", "Nội dung keo bonding đế giày dùng cho kiểm tra.")
    doc = new_doc("lesson", {"topic": "keo bonding"})
    run(engine.make_outline(doc["id"]))
    fake.fail_sections = {"Nội dung chính"}

    async def go():
        assert write_jobs.start(doc["id"]) is True
        assert write_jobs.start(doc["id"]) is False          # already running
        await write_jobs.wait(doc["id"])
    run(go())
    st = write_jobs.snapshot(doc["id"])
    assert st["running"] is False and st["done"] == st["total"] == 3
    assert st["errors"] and st["errors"][0]["section"] == "Nội dung chính" and "quota" in st["errors"][0]["error"]
    d = store.get(doc["id"])
    assert d["sections"]["s2"]["status"] == "error" and d["sections"]["s1"]["status"] == "done"
    assert d["status"] == "outline"                           # not 'written' while a section failed

    fake.fail_sections = set()
    async def retry():
        write_jobs.start(doc["id"], only_missing=True)
        await write_jobs.wait(doc["id"])
    run(retry())
    assert write_jobs.snapshot(doc["id"])["total"] == 1        # s1 and s3 were already done; only the failed s2 is redone
    assert store.get(doc["id"])["status"] == "written"


# ------------------------------------------------------------------------- API
def test_studio_api_crud_patch_and_save_note(fake):
    from fastapi.testclient import TestClient
    from brain_app.main import app
    seed_note("Keo", "Nội dung keo bonding đế giày dùng cho kiểm tra.")
    with TestClient(app) as c:
        kinds = c.get("/api/studio/kinds").json()
        assert set(kinds) == {"lesson", "sop", "synthesis"} and kinds["sop"]["fields"][0]["key"] == "process_name"
        assert c.post("/api/studio/docs", json={"kind": "nope", "params": {}}).status_code == 400
        r = c.post("/api/studio/docs", json={"kind": "lesson", "params": {}})
        assert r.status_code == 400 and "Chủ đề" in r.json()["detail"]

        d = c.post("/api/studio/docs", json={"kind": "lesson", "params": {"topic": "keo bonding"}}).json()
        did = d["id"]
        assert d["title"] == "keo bonding" and d["status"] == "draft"
        d = c.post(f"/api/studio/docs/{did}/outline").json()
        assert len(d["outline"]) == 3
        c.post(f"/api/studio/docs/{did}/sections/s1/write")

        # reorder outline: written content follows its section
        o = d["outline"]
        d = c.patch(f"/api/studio/docs/{did}", json={"outline": [o[2], o[0], {"title": "Mục mới", "brief": ""}]}).json()
        assert [x["title"] for x in d["outline"]] == ["Bài tập", "Mục tiêu học tập", "Mục mới"]
        assert d["sections"]["s2"]["status"] == "done" and d["sections"]["s1"]["status"] == "pending"
        d = c.patch(f"/api/studio/docs/{did}", json={"sections": {"s1": "Tôi tự sửa."}}).json()
        assert d["sections"]["s1"]["edited"] is True and "Tôi tự sửa." in d["markdown"]

        n1 = c.post(f"/api/studio/docs/{did}/save-note", json={"category": "Resources", "tags": ["studio"]}).json()
        n2 = c.post(f"/api/studio/docs/{did}/save-note", json={"category": "Resources"}).json()
        assert n1["updated"] is False and n2["updated"] is True and n1["note_id"] == n2["note_id"]
        notes = c.get("/api/notes").json()
        assert sum(1 for n in notes if n["title"] == "keo bonding") == 1

        md = c.get(f"/api/studio/docs/{did}/markdown").json()
        assert md["filename"] == "keo-bonding.md" and md["markdown"].startswith("# keo bonding")
        assert c.get("/api/studio/docs/999").status_code == 404
        assert c.delete(f"/api/studio/docs/{did}").json()["success"] is True
        assert c.get(f"/api/studio/docs/{did}").status_code == 404


def test_studio_api_maps_llm_failure_to_502(fake):
    from fastapi.testclient import TestClient
    from brain_app.main import app

    async def boom(system, user, **kw):
        raise llm.LLMError("Gemini lỗi 429: hết quota")
    llm.complete = boom   # fixture's monkeypatch restores the original afterwards
    with TestClient(app) as c:
        did = c.post("/api/studio/docs", json={"kind": "lesson", "params": {"topic": "x"}}).json()["id"]
        r = c.post(f"/api/studio/docs/{did}/outline")
        assert r.status_code == 502 and "429" in r.json()["detail"]


# ----------------------------------------------------------------------- llm.py
GEM_OK = {"candidates": [{"content": {"parts": [{"text": "bí mật", "thought": True}, {"text": "xin chào"}]}}]}


def test_llm_gemini_request_shape_retry_and_errors(db, monkeypatch):
    set_setting("gemini_api_key", "AIzaSy-test-key-1234567890")
    set_setting("gemini_model", "gemini-3.8-flash")
    seen, n = [], {"c": 0}

    def handler(req):
        n["c"] += 1
        seen.append(req)
        return httpx.Response(429, json={"error": {"message": "q"}}) if n["c"] == 1 else httpx.Response(200, json=GEM_OK)

    async def nosleep(_): return None
    monkeypatch.setattr(llm, "_sleep", nosleep)
    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    out = run(llm.complete("SYS", "USER", json_mode=True))
    assert out == "xin chào" and n["c"] == 2
    req = seen[-1]
    body = json.loads(req.content)
    assert req.headers["x-goog-api-key"].startswith("AIzaSy") and "key=" not in str(req.url)
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["generationConfig"]["responseMimeType"] == "application/json"

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(lambda r: httpx.Response(404, json={"error": {"message": "gone"}})))
    with pytest.raises(llm.LLMError) as e:
        run(llm.complete("s", "u"))
    assert "404" in str(e.value) and "ngừng hỗ trợ" in str(e.value)
    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})))
    with pytest.raises(llm.LLMError) as e:
        run(llm.complete("s", "u"))
    assert "SAFETY" in str(e.value)


def test_llm_openrouter_drops_response_format_when_rejected(db, monkeypatch):
    set_setting("llm_provider", "openrouter")
    set_setting("openrouter_api_key", "sk-or-test-key")
    bodies = []

    def handler(req):
        b = json.loads(req.content)
        bodies.append(b)
        if "response_format" in b:
            return httpx.Response(400, json={"error": {"message": "unsupported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"a\": 1}"}}]})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    assert run(llm.complete_json("s", "u")) == {"a": 1}
    assert "response_format" in bodies[0] and "response_format" not in bodies[1]


def test_llm_not_configured_and_json_repair(db, monkeypatch):
    with pytest.raises(llm.LLMError) as e:
        run(llm.complete("s", "u"))
    assert "API key" in str(e.value)

    replies = iter(["xin lỗi, đây là câu trả lời", '```json\n{"ok": true}\n```'])
    calls = []

    async def fake_complete(system, user, **kw):
        calls.append(user)
        return next(replies)
    monkeypatch.setattr(llm, "complete", fake_complete)
    assert run(llm.complete_json("s", "u")) == {"ok": True}
    assert len(calls) == 2 and "Chỉ trả về JSON" in calls[1]
    assert llm.extract_json('Kết quả: {"a": [1, 2]} hết') == {"a": [1, 2]}
