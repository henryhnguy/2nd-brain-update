"""Persistence for Studio documents. Everything except title/status lives in one JSON blob."""
import copy
import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from brain_app.database import get_db_connection


def _blank(kind: str, params: Dict[str, Any], scope: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "params": params, "scope": scope,
        "outline": [],        # [{id, title, brief, sources?}]
        "sections": {},       # id -> {status: pending|done|error, content, error?, edited?}
        "sources": [],        # [{n, source_type, source_id, title}]
        "questions": [],      # SOP: [{id, question, why, answer}]
        "review": [],         # [{severity, section, issue, suggestion, kind}]
        "summaries": {},      # synthesis: str(n) -> summary
        "quality": {},        # citation check result
        "version": "0.1",
        "note_id": None,
        "warnings": [],
    }


def _row_to_doc(row) -> Dict[str, Any]:
    d = json.loads(row["data"] or "{}")
    d.update(id=row["id"], kind=row["kind"], title=row["title"], status=row["status"],
             created_at=row["created_at"], updated_at=row["updated_at"])
    return d


def create(kind: str, title: str, params: Dict[str, Any], scope: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO studio_docs (kind, title, status, data, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (kind, title, "draft", json.dumps(_blank(kind, params, scope), ensure_ascii=False), now, now))
    doc_id = cur.lastrowid
    conn.commit()
    conn.close()
    return get(doc_id)


def get(doc_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM studio_docs WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return _row_to_doc(row) if row else None


def list_docs() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    rows = conn.execute("SELECT id, kind, title, status, created_at, updated_at FROM studio_docs "
                        "ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete(doc_id: int) -> bool:
    conn = get_db_connection()
    conn.execute("DELETE FROM studio_versions WHERE doc_id = ?", (doc_id,))
    cur = conn.execute("DELETE FROM studio_docs WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def mutate(doc_id: int, fn: Callable[[Dict[str, Any]], Any]) -> Dict[str, Any]:
    """Atomic read-modify-write. `fn` edits the doc dict in place (it may also set doc['title'/'status'])."""
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM studio_docs WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            raise KeyError(doc_id)
        doc = _row_to_doc(row)
        fn(doc)
        data = {k: v for k, v in doc.items()
                if k not in ("id", "kind", "title", "status", "created_at", "updated_at")}
        now = datetime.utcnow().isoformat()
        conn.execute("UPDATE studio_docs SET title=?, status=?, data=?, updated_at=? WHERE id=?",
                     (doc["title"], doc["status"], json.dumps(data, ensure_ascii=False), now, doc_id))
        conn.commit()
        doc["updated_at"] = now
        return doc
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def add_version(doc_id: int, version: str, label: str, markdown: str):
    conn = get_db_connection()
    conn.execute("INSERT INTO studio_versions (doc_id, version, label, markdown, created_at) VALUES (?,?,?,?,?)",
                 (doc_id, version, label, markdown, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def list_versions(doc_id: int, with_markdown: bool = False) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cols = "id, version, label, created_at" + (", markdown" if with_markdown else "")
    rows = conn.execute(f"SELECT {cols} FROM studio_versions WHERE doc_id = ? ORDER BY id", (doc_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
