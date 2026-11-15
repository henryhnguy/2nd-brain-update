"""Studio pipelines: retrieval with a user-chosen scope, outline/question generation, section writing,
review, assembly. LLM access goes through brain_app.rag.llm (easy to fake in tests)."""
import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from brain_app.database import get_db_connection
from brain_app.rag import llm
from brain_app.rag.embeddings import EmbeddingError, embedding_service
from brain_app.rag.vector_store import vector_store
from brain_app.studio import prompts, quality, store
from brain_app.studio.kinds import KINDS, SOP_PROCEDURE_TITLE, SOP_TEMPLATE

MAX_SOURCES = 10          # synthesis: how many distinct sources are summarised
CONTEXT_CHARS = 9000      # cap on retrieved text per prompt
SECTION_TOP_K = 6


class StudioError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ------------------------------------------------------------------ retrieval
def resolve_scope(scope: Optional[Dict[str, Any]]) -> Optional[Set[Tuple[str, int]]]:
    """scope = {note_ids, document_ids, categories, tags}; empty/None = whole knowledge base."""
    scope = scope or {}
    note_ids = [int(x) for x in scope.get("note_ids") or []]
    doc_ids = [int(x) for x in scope.get("document_ids") or []]
    cats = [c for c in scope.get("categories") or [] if c]
    tags = [t for t in scope.get("tags") or [] if t]
    if not (note_ids or doc_ids or cats or tags):
        return None
    allowed: Set[Tuple[str, int]] = {("note", i) for i in note_ids} | {("document", i) for i in doc_ids}
    if cats or tags:
        conn = get_db_connection()
        rows = conn.execute("SELECT id, category, tags FROM notes").fetchall()
        conn.close()
        for r in rows:
            try:
                note_tags = json.loads(r["tags"]) if r["tags"] else []
            except Exception:
                note_tags = []
            if r["category"] in cats or any(t in note_tags for t in tags):
                allowed.add(("note", r["id"]))
    return allowed


async def retrieve(doc: Dict[str, Any], query: str, k: int = SECTION_TOP_K,
                   restrict: Optional[Set[Tuple[str, int]]] = None) -> List[Dict[str, Any]]:
    allowed = restrict if restrict is not None else resolve_scope(doc.get("scope"))
    if allowed is not None and not allowed:
        return []
    qv = None
    try:
        qv = await embedding_service.embed_query(query)
    except EmbeddingError:
        pass  # keyword-only retrieval still works
    return vector_store.hybrid_search(query, qv, model_tag=embedding_service.active_tag(), top_k=k, allowed=allowed)


def register_sources(doc_id: int, chunks: List[Dict[str, Any]]) -> Dict[Tuple[str, int], int]:
    """Give every distinct (type, id) a stable citation number [n] within this document."""
    numbering: Dict[Tuple[str, int], int] = {}

    def fn(doc):
        known = {(s["source_type"], s["source_id"]): s["n"] for s in doc["sources"]}
        for c in chunks:
            key = (c["source_type"], c["source_id"])
            if key not in known:
                n = max([s["n"] for s in doc["sources"]], default=0) + 1
                doc["sources"].append({"n": n, "source_type": key[0], "source_id": key[1], "title": c["source_title"]})
                known[key] = n
        numbering.update(known)

    store.mutate(doc_id, fn)
    return numbering


def context_block(chunks: List[Dict[str, Any]], numbering: Dict[Tuple[str, int], int]) -> str:
    out, used, seen = [], 0, set()
    for c in chunks:
        text = c["content"].strip()
        if text in seen:
            continue
        seen.add(text)
        n = numbering[(c["source_type"], c["source_id"])]
        kind = "Tài liệu" if c["source_type"] == "document" else "Ghi chú"
        piece = f"[{n}] {c['source_title']} ({kind})\n{text}\n"
        if used + len(piece) > CONTEXT_CHARS:
            break
        out.append(piece)
        used += len(piece)
    return "\n".join(out)


def _require_llm():
    if not llm.is_configured():
        raise StudioError("Chưa cấu hình API key cho mô hình AI (Cài đặt → Google Gemini hoặc OpenRouter).", 400)


def _llm_error(e: Exception) -> StudioError:
    return StudioError(str(e), 502)


def _set_outline(doc_id: int, items: List[Dict[str, Any]], status: str = "outline"):
    def fn(doc):
        doc["outline"] = [dict(it, id=f"s{i + 1}") for i, it in enumerate(items)]
        doc["sections"] = {o["id"]: {"status": "pending", "content": ""} for o in doc["outline"]}
        doc["quality"] = {}
        doc["review"] = []
        doc["status"] = status
    return store.mutate(doc_id, fn)


def _clean_items(raw: Any, with_sources: bool = False, max_n: int = 12) -> List[Dict[str, Any]]:
    secs = raw.get("sections") if isinstance(raw, dict) else raw
    items = []
    for s in secs or []:
        if not isinstance(s, dict) or not str(s.get("title", "")).strip():
            continue
        it = {"title": str(s["title"]).strip()[:120], "brief": str(s.get("brief", "")).strip()[:400]}
        if with_sources:
            it["sources"] = [int(x) for x in (s.get("sources") or []) if str(x).isdigit()]
        items.append(it)
    if len(items) < 2:
        raise StudioError("Mô hình trả về dàn ý không dùng được, hãy thử lại.", 502)
    return items[:max_n]


# ----------------------------------------------------------------- questions
async def make_questions(doc_id: int) -> Dict[str, Any]:
    doc = store.get(doc_id)
    if doc["kind"] != "sop":
        raise StudioError("Chỉ SOP có bước câu hỏi bổ sung.")
    _require_llm()
    p = doc["params"]
    chunks = await retrieve(doc, f"{p.get('process_name', '')} {p.get('standards', '')} {p.get('purpose', '')}", 8)
    numbering = register_sources(doc_id, chunks)
    try:
        raw = await llm.complete_json(*prompts.sop_questions(p, context_block(chunks, numbering)))
    except llm.LLMError as e:
        raise _llm_error(e)
    items = raw.get("questions") if isinstance(raw, dict) else raw
    qs = [{"id": f"q{i + 1}", "question": str(q.get("question", "")).strip(), "why": str(q.get("why", "")).strip(),
           "answer": ""} for i, q in enumerate(items or []) if isinstance(q, dict) and str(q.get("question", "")).strip()][:8]

    def fn(d):
        d["questions"] = qs
        d["status"] = "questions"
    return store.mutate(doc_id, fn)


# ------------------------------------------------------------------- outline
async def make_outline(doc_id: int) -> Dict[str, Any]:
    doc = store.get(doc_id)
    kind, p = doc["kind"], doc["params"]
    if kind == "sop":
        return _set_outline(doc_id, [dict(t) for t in SOP_TEMPLATE])
    _require_llm()
    if kind == "lesson":
        chunks = await retrieve(doc, f"{p.get('topic', '')} {p.get('objectives', '')}", 8)
        numbering = register_sources(doc_id, chunks)
        try:
            raw = await llm.complete_json(*prompts.lesson_outline(p, context_block(chunks, numbering)))
        except llm.LLMError as e:
            raise _llm_error(e)
        return _set_outline(doc_id, _clean_items(raw))
    return await _synthesis_outline(doc_id)


async def _synthesis_outline(doc_id: int) -> Dict[str, Any]:
    doc = store.get(doc_id)
    p = doc["params"]
    topic = p.get("topic", "")
    chunks = await retrieve(doc, topic, 40)
    if not chunks:
        raise StudioError("Không tìm thấy nội dung liên quan trong kho (hoặc ngoài phạm vi nguồn đã chọn).", 422)

    grouped: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for c in chunks:  # ranked order is preserved by dict insertion
        grouped.setdefault((c["source_type"], c["source_id"]), []).append(c)
    top = list(grouped.items())[:MAX_SOURCES]

    def reset(d):
        d["sources"] = []
        d["summaries"] = {}
        d["warnings"] = []
    store.mutate(doc_id, reset)
    flat = [c for _, cs in top for c in cs]
    numbering = register_sources(doc_id, flat)

    sem = asyncio.Semaphore(3)
    warnings: List[str] = []

    async def summarise(key, cs):
        n = numbering[key]
        text = "\n\n".join(c["content"] for c in cs[:3])[:4000]
        async with sem:
            try:
                return n, (await llm.complete(*prompts.source_summary(topic, cs[0]["source_title"], text),
                                              temperature=0.2, max_tokens=1024)).strip()
            except llm.LLMError as e:
                warnings.append(f"Không tóm tắt được nguồn [{n}] ({cs[0]['source_title']}): {e}. Dùng đoạn trích thô.")
                return n, text[:600]

    results = await asyncio.gather(*[summarise(k, cs) for k, cs in top])
    summaries = {str(n): s for n, s in results}
    numbered = "\n\n".join(f"[{n}] {next(x['title'] for x in store.get(doc_id)['sources'] if x['n'] == int(n))}\n{s}"
                           for n, s in sorted(summaries.items(), key=lambda kv: int(kv[0])))
    try:
        raw = await llm.complete_json(*prompts.synthesis_outline(p, numbered))
    except llm.LLMError as e:
        raise _llm_error(e)
    items = _clean_items(raw, with_sources=True, max_n=8)
    valid = {int(k) for k in summaries}
    for it in items:
        it["sources"] = [n for n in it["sources"] if n in valid] or sorted(valid)

    def save(d):
        d["summaries"] = summaries
        d["warnings"] = warnings
    store.mutate(doc_id, save)
    return _set_outline(doc_id, items)


# ------------------------------------------------------------------- writing
def _strip_leading_heading(text: str, title: str) -> str:
    lines = text.strip().splitlines()
    if lines and re.match(r"^#{1,6}\s+", lines[0]) and title.lower()[:12] in lines[0].lower():
        lines = lines[1:]
    return "\n".join(lines).strip()


async def write_section(doc_id: int, sid: str) -> Dict[str, Any]:
    doc = store.get(doc_id)
    section = next((o for o in doc["outline"] if o["id"] == sid), None)
    if not section:
        raise StudioError("Không có mục này trong dàn ý.", 404)
    _require_llm()
    kind, p = doc["kind"], doc["params"]
    query = f"{p.get('topic') or p.get('process_name', '')} {section['title']} {section.get('brief', '')}"

    restrict = None
    if kind == "synthesis":
        by_n = {s["n"]: (s["source_type"], s["source_id"]) for s in doc["sources"]}
        restrict = {by_n[n] for n in section.get("sources", []) if n in by_n}
    chunks = await retrieve(doc, query, SECTION_TOP_K, restrict=restrict)
    numbering = register_sources(doc_id, chunks)
    context = context_block(chunks, numbering)
    if kind == "synthesis":
        sums = "\n\n".join(f"[{n}] Tóm tắt nguồn:\n{doc['summaries'].get(str(n), '')}" for n in section.get("sources", []))
        context = f"{sums}\n\n{context}".strip()

    if kind == "lesson":
        system, user = prompts.lesson_section(p, doc["outline"], section, context)
    elif kind == "sop":
        system, user = prompts.sop_section(p, doc["outline"], section, doc["questions"], context)
    else:
        system, user = prompts.synthesis_section(p, doc["outline"], section, context)

    try:
        text = await llm.complete(system, user, temperature=0.3)
    except llm.LLMError as e:
        def fail(d):
            d["sections"][sid] = {"status": "error", "content": d["sections"].get(sid, {}).get("content", ""), "error": str(e)}
        store.mutate(doc_id, fail)
        raise _llm_error(e)

    content = _strip_leading_heading(text, section["title"])

    def ok(d):
        d["sections"][sid] = {"status": "done", "content": content}
        if all(s.get("status") == "done" for s in d["sections"].values()):
            d["status"] = "written"
            d["quality"] = quality.check_citations(d) if d["kind"] != "sop" else {}
    return store.mutate(doc_id, ok)


# -------------------------------------------------------------------- review
async def review(doc_id: int) -> Dict[str, Any]:
    doc = store.get(doc_id)
    findings: List[Dict[str, str]] = []
    if doc["kind"] == "sop":
        findings = quality.sop_checks(doc, SOP_PROCEDURE_TITLE)
        if llm.is_configured() and any((s.get("content") or "").strip() for s in doc["sections"].values()):
            try:
                raw = await llm.complete_json(*prompts.sop_review(doc["params"], assemble(doc, with_sources=False)))
                for f in (raw.get("findings") if isinstance(raw, dict) else raw) or []:
                    if isinstance(f, dict) and f.get("issue"):
                        findings.append({"severity": str(f.get("severity", "medium")).lower(), "kind": "ai",
                                         "section": str(f.get("section", "")), "issue": str(f["issue"]),
                                         "suggestion": str(f.get("suggestion", ""))})
            except llm.LLMError as e:
                findings.append({"severity": "low", "kind": "ai_error", "section": "",
                                 "issue": f"Rà soát bằng AI không chạy được: {e}", "suggestion": "Thử lại sau."})
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: order.get(f["severity"], 1))

    def fn(d):
        d["review"] = findings
        if d["kind"] != "sop":
            d["quality"] = quality.check_citations(d)
        if d["status"] == "written":
            d["status"] = "reviewed"
    return store.mutate(doc_id, fn)


# ------------------------------------------------------------------ assembly
def _meta_line(doc: Dict[str, Any]) -> str:
    p = doc["params"]
    if doc["kind"] == "lesson":
        bits = [("Đối tượng", p.get("audience")), ("Trình độ", p.get("level")),
                ("Thời lượng", f"{p['duration_min']} phút" if p.get("duration_min") else None)]
    elif doc["kind"] == "synthesis":
        bits = [("Mục tiêu", p.get("goal")), ("Người đọc", p.get("audience"))]
    else:
        return ""
    line = " · ".join(f"**{k}:** {v}" for k, v in bits if v)
    return f"> {line}\n" if line else ""


def assemble(doc: Dict[str, Any], with_sources: bool = True) -> str:
    kind = doc["kind"]
    heading = f"SOP: {doc['title']}" if kind == "sop" and not doc["title"].lower().startswith("sop") else doc["title"]
    parts = [f"# {heading}\n"]
    if kind == "sop":
        p = doc["params"]
        versions = store.list_versions(doc["id"]) if doc.get("id") else []
        ver = versions[-1]["version"] if versions else f"{doc.get('version', '0.1')} (bản nháp)"
        parts.append("| Phiên bản | Ngày | Bộ phận |\n|---|---|---|\n"
                     f"| {ver} | {datetime.utcnow().strftime('%d/%m/%Y')} | {p.get('department') or '—'} |\n")
    else:
        m = _meta_line(doc)
        if m:
            parts.append(m)

    body_texts = []
    for o in doc["outline"]:
        sec = doc["sections"].get(o["id"], {})
        content = (sec.get("content") or "").strip()
        body_texts.append(content)
        parts.append(f"## {o['title']}\n\n{content if content else '*(chưa viết)*'}\n")

    if kind == "sop" and doc.get("id"):
        versions = store.list_versions(doc["id"])
        if versions:
            rows = "\n".join(f"| {v['version']} | {v['created_at'][:10]} | {v['label'] or '—'} |" for v in versions)
            parts.append(f"## Lịch sử sửa đổi\n\n| Phiên bản | Ngày | Nội dung thay đổi |\n|---|---|---|\n{rows}\n")

    if with_sources:
        used = set()
        for t in body_texts:
            used |= quality.cited_numbers(t)
        refs = [s for s in sorted(doc["sources"], key=lambda s: s["n"]) if s["n"] in used]
        if refs:
            lines = "\n".join(f"{s['n']}. {s['title']} ({'tài liệu' if s['source_type'] == 'document' else 'ghi chú'})" for s in refs)
            parts.append(f"## Nguồn tham khảo\n\n{lines}\n")
    return "\n".join(parts).strip() + "\n"


def next_version(doc_id: int, bump: str) -> str:
    versions = store.list_versions(doc_id)
    if not versions:
        return "1.0"
    try:
        major, minor = [int(x) for x in versions[-1]["version"].split(".")[:2]]
    except Exception:
        major, minor = len(versions), 0
    return f"{major + 1}.0" if bump == "major" else f"{major}.{minor + 1}"
