from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from brain_app.database import get_db_connection
from brain_app.rag.rag_service import rag_service
from brain_app.studio import engine, store
from brain_app.studio.engine import StudioError
from brain_app.studio.jobs import write_jobs
from brain_app.studio.kinds import KINDS

router = APIRouter(prefix="/api/studio", tags=["studio"])


class CreateDoc(BaseModel):
    kind: str
    params: Dict[str, Any] = {}
    scope: Dict[str, Any] = {}
    title: Optional[str] = None


class PatchDoc(BaseModel):
    title: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    scope: Optional[Dict[str, Any]] = None
    outline: Optional[List[Dict[str, Any]]] = None       # reorder / rename / add / remove sections
    sections: Optional[Dict[str, str]] = None            # sid -> manually edited markdown
    answers: Optional[Dict[str, str]] = None             # question id -> answer


class WriteBody(BaseModel):
    all: bool = False   # True: rewrite every section, False: only the missing ones


class VersionBody(BaseModel):
    label: str = ""
    bump: str = "minor"  # 'minor' | 'major'


class SaveNoteBody(BaseModel):
    category: str = "Resources"
    tags: List[str] = []


def _doc_or_404(doc_id: int) -> Dict[str, Any]:
    doc = store.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu Studio")
    return doc


def _view(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {**doc, "markdown": engine.assemble(doc), "job": write_jobs.snapshot(doc["id"]),
            "versions": store.list_versions(doc["id"])}


async def _run(coro):
    try:
        return await coro
    except StudioError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/kinds")
def kinds():
    return {k: {kk: vv for kk, vv in v.items() if kk != "title_from"} | {"id": k} for k, v in KINDS.items()}


@router.get("/docs")
def list_docs():
    return store.list_docs()


@router.post("/docs")
def create_doc(body: CreateDoc):
    kind = KINDS.get(body.kind)
    if not kind:
        raise HTTPException(status_code=400, detail=f"kind phải thuộc {list(KINDS)}")
    missing = [f["label"] for f in kind["fields"] if f.get("required") and not str(body.params.get(f["key"], "")).strip()]
    if missing:
        raise HTTPException(status_code=400, detail=f"Thiếu thông tin bắt buộc: {', '.join(missing)}")
    title = (body.title or str(body.params.get(kind["title_from"], "")).strip() or kind["label"])[:150]
    return _view(store.create(body.kind, title, body.params, body.scope))


@router.get("/docs/{doc_id}")
def get_doc(doc_id: int):
    return _view(_doc_or_404(doc_id))


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: int):
    _doc_or_404(doc_id)
    store.delete(doc_id)
    return {"success": True}


@router.patch("/docs/{doc_id}")
def patch_doc(doc_id: int, body: PatchDoc):
    _doc_or_404(doc_id)

    def fn(d):
        if body.title is not None and body.title.strip():
            d["title"] = body.title.strip()[:150]
        if body.params is not None:
            d["params"] = {**d["params"], **body.params}
        if body.scope is not None:
            d["scope"] = body.scope
        if body.outline is not None:
            items = [{"title": str(o.get("title", "")).strip(), "brief": str(o.get("brief", "")).strip(),
                      **({"sources": o["sources"]} if o.get("sources") is not None else {}),
                      "_old": o.get("id")} for o in body.outline if str(o.get("title", "")).strip()]
            old_sections = d["sections"]
            d["outline"], d["sections"] = [], {}
            for i, it in enumerate(items):
                sid = f"s{i + 1}"
                old = old_sections.get(it.pop("_old", None)) or {"status": "pending", "content": ""}
                d["outline"].append({**it, "id": sid})
                d["sections"][sid] = old
        if body.sections:
            for sid, text in body.sections.items():
                if sid in d["sections"]:
                    d["sections"][sid] = {"status": "done", "content": text, "edited": True}
        if body.answers:
            for q in d["questions"]:
                if q["id"] in body.answers:
                    q["answer"] = body.answers[q["id"]]
    return _view(store.mutate(doc_id, fn))


@router.post("/docs/{doc_id}/questions")
async def make_questions(doc_id: int):
    _doc_or_404(doc_id)
    await _run(engine.make_questions(doc_id))
    return _view(store.get(doc_id))


@router.post("/docs/{doc_id}/outline")
async def make_outline(doc_id: int):
    _doc_or_404(doc_id)
    await _run(engine.make_outline(doc_id))
    return _view(store.get(doc_id))


@router.post("/docs/{doc_id}/sections/{sid}/write")
async def write_section(doc_id: int, sid: str):
    _doc_or_404(doc_id)
    await _run(engine.write_section(doc_id, sid))
    return _view(store.get(doc_id))


@router.post("/docs/{doc_id}/write")
async def write_all(doc_id: int, body: WriteBody = WriteBody()):
    doc = _doc_or_404(doc_id)
    if not doc["outline"]:
        raise HTTPException(status_code=400, detail="Chưa có dàn ý.")
    started = write_jobs.start(doc_id, only_missing=not body.all)
    return {"started": started, **_view(store.get(doc_id))}


@router.post("/docs/{doc_id}/review")
async def review(doc_id: int):
    _doc_or_404(doc_id)
    await _run(engine.review(doc_id))
    return _view(store.get(doc_id))


@router.get("/docs/{doc_id}/markdown")
def get_markdown(doc_id: int):
    doc = _doc_or_404(doc_id)
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in doc["title"]).strip().replace(" ", "-")[:60] or "tai-lieu"
    return {"filename": f"{safe}.md", "markdown": engine.assemble(doc)}


@router.post("/docs/{doc_id}/versions")
def snapshot(doc_id: int, body: VersionBody):
    doc = _doc_or_404(doc_id)
    if not any((s.get("content") or "").strip() for s in doc["sections"].values()):
        raise HTTPException(status_code=400, detail="Chưa có nội dung để lưu phiên bản.")
    version = engine.next_version(doc_id, body.bump)
    store.add_version(doc_id, version, body.label.strip(), "")   # placeholder row so the history table includes it
    markdown = engine.assemble(store.get(doc_id))
    conn = get_db_connection()
    conn.execute("UPDATE studio_versions SET markdown = ? WHERE doc_id = ? AND version = ?", (markdown, doc_id, version))
    conn.commit()
    conn.close()
    store.mutate(doc_id, lambda d: d.__setitem__("version", version))
    return _view(store.get(doc_id))


@router.get("/docs/{doc_id}/versions/{version}")
def get_version(doc_id: int, version: str):
    _doc_or_404(doc_id)
    for v in store.list_versions(doc_id, with_markdown=True):
        if v["version"] == version:
            return v
    raise HTTPException(status_code=404, detail="Không có phiên bản này")


@router.post("/docs/{doc_id}/save-note")
async def save_as_note(doc_id: int, body: SaveNoteBody):
    doc = _doc_or_404(doc_id)
    markdown = engine.assemble(doc)
    now = datetime.utcnow().isoformat()
    import json as _json
    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM notes WHERE id = ?", (doc.get("note_id"),)).fetchone() if doc.get("note_id") else None
    if existing:
        conn.execute("UPDATE notes SET title=?, content=?, category=?, tags=?, updated_at=? WHERE id=?",
                     (doc["title"], markdown, body.category, _json.dumps(body.tags, ensure_ascii=False), now, existing["id"]))
        note_id = existing["id"]
    else:
        cur = conn.execute("INSERT INTO notes (title, content, category, tags, pinned, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                           (doc["title"], markdown, body.category, _json.dumps(body.tags, ensure_ascii=False), 0, now, now))
        note_id = cur.lastrowid
    conn.commit()
    conn.close()
    await rag_service.index_note(note_id, doc["title"], markdown, body.category, body.tags)
    store.mutate(doc_id, lambda d: d.__setitem__("note_id", note_id))
    return {"success": True, "note_id": note_id, "updated": bool(existing)}
