from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from brain_app.ontology import store

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


class TermCreate(BaseModel):
    name: str
    kind: str = "concept"
    definition: str = ""
    aliases: List[str] = Field(default_factory=list)


class TermUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    definition: Optional[str] = None
    aliases: Optional[List[str]] = None


class RelationCreate(BaseModel):
    from_id: int
    to_id: int
    kind: str
    note: str = ""


class EvidenceCreate(BaseModel):
    source_type: str
    source_id: int
    quote: str


class SuggestRequest(BaseModel):
    document_ids: Optional[List[int]] = None
    limit: int = 40
    min_sources: int = 2


class AcceptRequest(BaseModel):
    candidates: List[Dict[str, Any]]


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except store.OntologyError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/meta")
def meta():
    return {"kinds": store.KINDS, "relation_kinds": store.REL_KINDS}


@router.get("/terms")
def list_terms(status: Optional[str] = None, q: str = "", kind: Optional[str] = None):
    return store.list_terms(status=status, q=q, kind=kind)


@router.post("/terms")
def create_term(body: TermCreate):
    return _run(store.create_term, body.name, body.kind, body.definition, body.aliases)


@router.get("/terms/{term_id}")
def get_term(term_id: int):
    return _run(store.get_term, term_id)


@router.patch("/terms/{term_id}")
def update_term(term_id: int, body: TermUpdate):
    return _run(store.update_term, term_id, body.name, body.kind, body.definition, body.aliases)


@router.post("/terms/{term_id}/approve")
def approve(term_id: int):
    return _run(store.set_status, term_id, True)


@router.post("/terms/{term_id}/unapprove")
def unapprove(term_id: int):
    return _run(store.set_status, term_id, False)


@router.delete("/terms/{term_id}")
def delete_term(term_id: int):
    _run(store.delete_term, term_id)
    return {"success": True}


@router.post("/relations")
def add_relation(body: RelationCreate):
    return _run(store.add_relation, body.from_id, body.to_id, body.kind, body.note)


@router.delete("/relations/{rel_id}")
def delete_relation(rel_id: int):
    store.delete_relation(rel_id)
    return {"success": True}


@router.post("/terms/{term_id}/evidence")
def add_evidence(term_id: int, body: EvidenceCreate):
    return _run(store.add_evidence, term_id, body.source_type, body.source_id, body.quote)


@router.delete("/evidence/{evidence_id}")
def delete_evidence(evidence_id: int):
    store.delete_evidence(evidence_id)
    return {"success": True}


@router.post("/suggest")
def suggest(body: SuggestRequest):
    return store.suggest_candidates(body.document_ids, max(1, min(body.limit, 100)), max(1, body.min_sources))


@router.post("/suggest/accept")
def suggest_accept(body: AcceptRequest):
    return store.accept_candidates(body.candidates)


@router.get("/resolve")
def resolve(text: str):
    return [{"id": t["id"], "name": t["name"], "matched": t["matched"], "definition": t["definition"]}
            for t in store.match_terms(text)]


@router.get("/graph")
def graph():
    return store.graph()


@router.get("/export")
def export(format: str = "json"):
    if format == "md":
        return PlainTextResponse(store.export_markdown(), media_type="text/markdown; charset=utf-8")
    return store.export_all()


@router.post("/import")
def import_(data: Dict[str, Any]):
    return _run(store.import_all, data)
