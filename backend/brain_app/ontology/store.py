"""Ontology cho Second Brain: thuật ngữ + quan hệ + dẫn chứng, do người duyệt.

Nguyên tắc:
  * Chỉ thuật ngữ đã DUYỆT (status = 'approved') mới ảnh hưởng tới tìm kiếm / chat / Studio.
  * Nháp (draft) chỉ để bạn soạn, không bao giờ lọt vào câu trả lời của AI.
  * Dẫn chứng (evidence) là câu trích nguyên văn từ tài liệu/ghi chú; hệ thống kiểm tra câu đó có
    thật trong nguồn (verified) chứ không tin lời AI.
  * Mọi hàm dùng trong đường tìm kiếm/chat đều không ném lỗi: ontology hỏng thì app chạy như cũ.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from brain_app.database import get_db_connection

KINDS = ["concept", "standard", "process", "defect", "material", "component", "organization", "other"]
REL_KINDS = ["is_a", "part_of", "related_to", "requires", "measured_by", "caused_by", "supersedes"]
SOURCE_TYPES = ["note", "document"]


class OntologyError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return datetime.utcnow().isoformat()


def fold(text: str) -> str:
    """Hạ chữ thường, bỏ dấu tiếng Việt, gộp khoảng trắng: để so khớp không phân biệt dấu/hoa thường."""
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- đọc

def _aliases_map(conn, term_ids: Optional[Iterable[int]] = None) -> Dict[int, List[Dict[str, Any]]]:
    rows = conn.execute("SELECT id, term_id, alias FROM ontology_aliases ORDER BY alias").fetchall()
    wanted = set(term_ids) if term_ids is not None else None
    out: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if wanted is None or r["term_id"] in wanted:
            out[r["term_id"]].append({"id": r["id"], "alias": r["alias"]})
    return out


def _term_row(r, aliases: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": r["id"], "name": r["name"], "kind": r["kind"], "definition": r["definition"],
        "status": r["status"], "approved_at": r["approved_at"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "aliases": [a["alias"] for a in aliases],
    }


def list_terms(status: Optional[str] = None, q: str = "", kind: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        sql, params = "SELECT * FROM ontology_terms WHERE 1=1", []
        if status in ("draft", "approved"):
            sql += " AND status = ?"
            params.append(status)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        rows = conn.execute(sql + " ORDER BY name COLLATE NOCASE", params).fetchall()
        amap = _aliases_map(conn)
        ev = {r["term_id"]: r["n"] for r in conn.execute(
            "SELECT term_id, COUNT(*) n FROM ontology_evidence WHERE verified = 1 GROUP BY term_id")}
        rel = defaultdict(int)
        for r in conn.execute("SELECT from_id, to_id FROM ontology_relations"):
            rel[r["from_id"]] += 1
            rel[r["to_id"]] += 1
        out = []
        qf = fold(q)
        for r in rows:
            t = _term_row(r, amap.get(r["id"], []))
            if qf and qf not in fold(" ".join([t["name"], t["definition"], *t["aliases"]])):
                continue
            t["verified_evidence"] = ev.get(r["id"], 0)
            t["relation_count"] = rel.get(r["id"], 0)
            out.append(t)
        return out
    finally:
        conn.close()


def get_term(term_id: int) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        r = conn.execute("SELECT * FROM ontology_terms WHERE id = ?", (term_id,)).fetchone()
        if not r:
            raise OntologyError("Không tìm thấy thuật ngữ", 404)
        t = _term_row(r, _aliases_map(conn, [term_id]).get(term_id, []))
        t["relations"] = [dict(x) for x in conn.execute("""
            SELECT rel.id AS id, rel.kind AS kind, rel.note AS note, 'out' AS direction, o.id AS other_id, o.name AS other_name, o.status AS other_status
            FROM ontology_relations rel JOIN ontology_terms o ON o.id = rel.to_id WHERE rel.from_id = ?
            UNION ALL
            SELECT rel.id, rel.kind, rel.note, 'in' AS direction, o.id, o.name, o.status
            FROM ontology_relations rel JOIN ontology_terms o ON o.id = rel.from_id WHERE rel.to_id = ?
            ORDER BY direction, kind""", (term_id, term_id)).fetchall()]
        t["evidence"] = [dict(x) for x in conn.execute(
            "SELECT * FROM ontology_evidence WHERE term_id = ? ORDER BY id", (term_id,)).fetchall()]
        return t
    finally:
        conn.close()


# --------------------------------------------------------------------------- ghi

def _check_name_free(conn, name: str, exclude_term: Optional[int] = None):
    key = fold(name)
    if not key:
        raise OntologyError("Tên thuật ngữ không được để trống")
    for r in conn.execute("SELECT id, name FROM ontology_terms"):
        if r["id"] != exclude_term and fold(r["name"]) == key:
            raise OntologyError(f"Đã có thuật ngữ '{r['name']}'", 409)
    for r in conn.execute("""SELECT a.alias, t.id tid, t.name tname FROM ontology_aliases a
                             JOIN ontology_terms t ON t.id = a.term_id"""):
        if r["tid"] != exclude_term and fold(r["alias"]) == key:
            raise OntologyError(f"'{name}' đã là tên gọi khác của '{r['tname']}'", 409)


def _clean_aliases(name: str, aliases: Optional[List[str]]) -> List[str]:
    seen, out = {fold(name)}, []
    for a in aliases or []:
        a = (a or "").strip()
        if a and fold(a) not in seen:
            seen.add(fold(a))
            out.append(a[:120])
    return out[:20]


def create_term(name: str, kind: str = "concept", definition: str = "", aliases: Optional[List[str]] = None) -> Dict[str, Any]:
    name = (name or "").strip()[:160]
    if kind not in KINDS:
        raise OntologyError(f"Loại không hợp lệ. Chọn: {', '.join(KINDS)}")
    conn = get_db_connection()
    try:
        _check_name_free(conn, name)
        als = _clean_aliases(name, aliases)
        for a in als:
            _check_name_free(conn, a)
        now = _now()
        cur = conn.execute(
            "INSERT INTO ontology_terms (name, kind, definition, status, created_at, updated_at) VALUES (?, ?, ?, 'draft', ?, ?)",
            (name, kind, (definition or "").strip(), now, now))
        tid = cur.lastrowid
        for a in als:
            conn.execute("INSERT INTO ontology_aliases (term_id, alias) VALUES (?, ?)", (tid, a))
        conn.commit()
    finally:
        conn.close()
    return get_term(tid)


def update_term(term_id: int, name: Optional[str] = None, kind: Optional[str] = None,
                definition: Optional[str] = None, aliases: Optional[List[str]] = None) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        r = conn.execute("SELECT * FROM ontology_terms WHERE id = ?", (term_id,)).fetchone()
        if not r:
            raise OntologyError("Không tìm thấy thuật ngữ", 404)
        new_name = r["name"] if name is None else name.strip()[:160]
        if name is not None:
            _check_name_free(conn, new_name, exclude_term=term_id)
        if kind is not None and kind not in KINDS:
            raise OntologyError(f"Loại không hợp lệ. Chọn: {', '.join(KINDS)}")
        if aliases is not None:
            als = _clean_aliases(new_name, aliases)
            for a in als:
                _check_name_free(conn, a, exclude_term=term_id)
            conn.execute("DELETE FROM ontology_aliases WHERE term_id = ?", (term_id,))
            for a in als:
                conn.execute("INSERT INTO ontology_aliases (term_id, alias) VALUES (?, ?)", (term_id, a))
        new_def = r["definition"] if definition is None else definition.strip()
        if r["status"] == "approved" and not new_def:
            raise OntologyError("Thuật ngữ đã duyệt phải có định nghĩa. Hãy bỏ duyệt trước nếu muốn xoá định nghĩa")
        conn.execute("UPDATE ontology_terms SET name = ?, kind = ?, definition = ?, updated_at = ? WHERE id = ?",
                     (new_name, kind or r["kind"], new_def, _now(), term_id))
        conn.commit()
    finally:
        conn.close()
    return get_term(term_id)


def set_status(term_id: int, approved: bool) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        r = conn.execute("SELECT * FROM ontology_terms WHERE id = ?", (term_id,)).fetchone()
        if not r:
            raise OntologyError("Không tìm thấy thuật ngữ", 404)
        if approved and len((r["definition"] or "").strip()) < 10:
            raise OntologyError("Cần viết định nghĩa (ít nhất 10 ký tự) trước khi duyệt")
        conn.execute("UPDATE ontology_terms SET status = ?, approved_at = ?, updated_at = ? WHERE id = ?",
                     ("approved" if approved else "draft", _now() if approved else None, _now(), term_id))
        conn.commit()
    finally:
        conn.close()
    return get_term(term_id)


def delete_term(term_id: int):
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM ontology_terms WHERE id = ?", (term_id,)).fetchone():
            raise OntologyError("Không tìm thấy thuật ngữ", 404)
        conn.execute("DELETE FROM ontology_aliases WHERE term_id = ?", (term_id,))
        conn.execute("DELETE FROM ontology_relations WHERE from_id = ? OR to_id = ?", (term_id, term_id))
        conn.execute("DELETE FROM ontology_evidence WHERE term_id = ?", (term_id,))
        conn.execute("DELETE FROM ontology_terms WHERE id = ?", (term_id,))
        conn.commit()
    finally:
        conn.close()


def add_relation(from_id: int, to_id: int, kind: str, note: str = "") -> Dict[str, Any]:
    if kind not in REL_KINDS:
        raise OntologyError(f"Loại quan hệ không hợp lệ. Chọn: {', '.join(REL_KINDS)}")
    if from_id == to_id:
        raise OntologyError("Không thể nối một thuật ngữ với chính nó")
    conn = get_db_connection()
    try:
        for tid in (from_id, to_id):
            if not conn.execute("SELECT 1 FROM ontology_terms WHERE id = ?", (tid,)).fetchone():
                raise OntologyError("Không tìm thấy thuật ngữ trong quan hệ", 404)
        if conn.execute("SELECT 1 FROM ontology_relations WHERE from_id = ? AND to_id = ? AND kind = ?",
                        (from_id, to_id, kind)).fetchone():
            raise OntologyError("Quan hệ này đã có", 409)
        cur = conn.execute("INSERT INTO ontology_relations (from_id, to_id, kind, note) VALUES (?, ?, ?, ?)",
                           (from_id, to_id, kind, (note or "").strip()[:300]))
        conn.commit()
        return {"id": cur.lastrowid, "from_id": from_id, "to_id": to_id, "kind": kind, "note": note}
    finally:
        conn.close()


def delete_relation(rel_id: int):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM ontology_relations WHERE id = ?", (rel_id,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- dẫn chứng

def _source_chunks(conn, source_type: str, source_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT source_title, content FROM chunks WHERE source_type = ? AND source_id = ? ORDER BY chunk_index",
                        (source_type, source_id)).fetchall()
    return [dict(r) for r in rows]


def verify_quote(quote: str, chunks: List[Dict[str, Any]]) -> bool:
    """Câu trích phải xuất hiện nguyên văn (bỏ qua dấu/hoa thường/khoảng trắng) trong nguồn."""
    q = fold(quote)
    if len(q) < 8:
        return False
    joined = fold(" ".join(c["content"] for c in chunks))
    return q in joined


def add_evidence(term_id: int, source_type: str, source_id: int, quote: str) -> Dict[str, Any]:
    if source_type not in SOURCE_TYPES:
        raise OntologyError("source_type phải là 'note' hoặc 'document'")
    quote = (quote or "").strip()
    if len(quote) < 8:
        raise OntologyError("Câu trích quá ngắn")
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM ontology_terms WHERE id = ?", (term_id,)).fetchone():
            raise OntologyError("Không tìm thấy thuật ngữ", 404)
        chunks = _source_chunks(conn, source_type, source_id)
        if not chunks:
            raise OntologyError("Không tìm thấy nguồn (hoặc nguồn chưa được lập chỉ mục)", 404)
        verified = 1 if verify_quote(quote, chunks) else 0
        cur = conn.execute(
            "INSERT INTO ontology_evidence (term_id, source_type, source_id, source_title, quote, verified, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (term_id, source_type, source_id, chunks[0]["source_title"], quote[:600], verified, _now()))
        conn.commit()
        return {"id": cur.lastrowid, "verified": bool(verified), "source_title": chunks[0]["source_title"]}
    finally:
        conn.close()


def delete_evidence(evidence_id: int):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM ontology_evidence WHERE id = ?", (evidence_id,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- khớp thuật ngữ (đường nóng)

def _approved_index(conn) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM ontology_terms WHERE status = 'approved'").fetchall()
    amap = _aliases_map(conn, [r["id"] for r in rows])
    return [_term_row(r, amap.get(r["id"], [])) for r in rows]


def _find_matches(text: str, terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    folded = fold(text)
    if not folded:
        return []
    out = []
    for t in terms:
        for phrase in [t["name"], *t["aliases"]]:
            p = fold(phrase)
            if p and re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", folded):
                out.append({**t, "matched": phrase})
                break
    return out


def match_terms(text: str) -> List[Dict[str, Any]]:
    """Các thuật ngữ ĐÃ DUYỆT xuất hiện trong text (theo tên hoặc tên gọi khác)."""
    conn = get_db_connection()
    try:
        return _find_matches(text, _approved_index(conn))
    finally:
        conn.close()


def expand_query(text: str, max_extra: int = 8) -> str:
    """Thêm tên chuẩn + tên gọi khác của thuật ngữ đã duyệt vào câu hỏi (chỉ cho phần tìm từ khoá).

    Lỗi bất kỳ -> trả lại nguyên văn câu hỏi.
    """
    try:
        matches = match_terms(text)
        if not matches:
            return text
        present = set(re.findall(r"\w+", fold(text)))
        extra: List[str] = []
        for t in matches:
            for phrase in [t["name"], *t["aliases"]]:
                for w in re.findall(r"\w+", fold(phrase)):
                    if w not in present and w not in extra:
                        extra.append(w)
        return (text + " " + " ".join(extra[:max_extra * 3])).strip() if extra else text
    except Exception as e:  # noqa: BLE001 - không để ontology làm hỏng tìm kiếm
        print(f"[ontology] expand_query skipped: {e}")
        return text


def glossary_block(text: str, limit: int = 6) -> str:
    """Khối 'thuật ngữ đã duyệt' đưa vào ngữ cảnh của AI. '' nếu không có gì khớp."""
    try:
        conn = get_db_connection()
        try:
            index = _approved_index(conn)
            matches = _find_matches(text, index)[:limit]
            if not matches:
                return ""
            by_id = {t["id"]: t for t in index}
            lines = []
            for t in matches:
                rels = []
                for r in conn.execute("SELECT from_id, to_id, kind FROM ontology_relations WHERE from_id = ? OR to_id = ?",
                                      (t["id"], t["id"])):
                    other = by_id.get(r["to_id"] if r["from_id"] == t["id"] else r["from_id"])
                    if other:
                        arrow = f"{r['kind']} → {other['name']}" if r["from_id"] == t["id"] else f"{other['name']} → {r['kind']} (đến đây)"
                        rels.append(arrow)
                alias = f" (còn gọi: {', '.join(t['aliases'][:4])})" if t["aliases"] else ""
                rel = f" Quan hệ: {'; '.join(rels[:4])}." if rels else ""
                lines.append(f"- **{t['name']}**{alias} [{t['kind']}]: {t['definition']}{rel}")
        finally:
            conn.close()
        return "[Thuật ngữ đã duyệt (ontology): dùng đúng nghĩa này khi trả lời]\n" + "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        print(f"[ontology] glossary skipped: {e}")
        return ""


# --------------------------------------------------------------------------- gợi ý thuật ngữ từ tài liệu

_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:[-./][A-Z0-9]+)*\b")
_PHRASE_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,3}\b")
_STOP_CODES = {"THE", "AND", "FOR", "NOT", "ALL", "PDF", "THIS", "WITH", "FROM", "ARE", "BUT", "YES", "NO",
               "NA", "TBD", "XLS", "XLSX", "DOC", "DOCX", "PPT", "PPTX", "CSV", "USD", "VND", "JAN", "FEB", "MAR",
               "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "ID", "OK", "PM", "AM"}
_STOP_FIRST = {"The", "This", "That", "These", "Those", "For", "And", "With", "From", "Please", "Note", "See",
               "Date", "Page", "Sheet", "Table", "Figure", "Nhóm", "Nguồn"}


def _sentence_around(content: str, start: int, end: int, span: int = 240) -> str:
    lo = max(0, start - span // 2)
    hi = min(len(content), end + span // 2)
    for sep in (". ", "\n"):
        k = content.rfind(sep, lo, start)
        if k != -1:
            lo = k + len(sep)
            break
    for sep in (". ", "\n"):
        k = content.find(sep, end, hi)
        if k != -1:
            hi = k + 1 if sep == ". " else k
            break
    return re.sub(r"\s+", " ", content[lo:hi]).strip()


def suggest_candidates(document_ids: Optional[List[int]] = None, limit: int = 40, min_sources: int = 2) -> List[Dict[str, Any]]:
    """Tìm ứng viên thuật ngữ (mã/viết tắt như AQL, QMS-FTW.06 và cụm viết hoa như 'Hot Melt') lặp lại ở nhiều nguồn.

    Thuần thống kê, chạy offline, không cần API key. Mỗi ứng viên kèm một câu trích nguyên văn từ nguồn.
    """
    conn = get_db_connection()
    try:
        sql, params = "SELECT source_type, source_id, source_title, content FROM chunks", []
        if document_ids:
            sql += " WHERE source_type = 'document' AND source_id IN (%s)" % ",".join("?" * len(document_ids))
            params = [int(i) for i in document_ids]
        rows = conn.execute(sql, params).fetchall()
        known = set()
        for r in conn.execute("SELECT name FROM ontology_terms"):
            known.add(fold(r["name"]))
        for r in conn.execute("SELECT alias FROM ontology_aliases"):
            known.add(fold(r["alias"]))
    finally:
        conn.close()

    freq: Dict[str, int] = defaultdict(int)
    srcs: Dict[str, set] = defaultdict(set)
    first: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        content = r["content"] or ""
        for rx in (_CODE_RE, _PHRASE_RE):
            for m in rx.finditer(content):
                tok = m.group(0)
                if rx is _CODE_RE:
                    if tok in _STOP_CODES or sum(ch.isdigit() for ch in tok) > len(tok) / 2:
                        continue
                else:
                    words = tok.split()
                    while words and words[0] in _STOP_FIRST:
                        words.pop(0)
                    if len(words) < 2:
                        continue
                    tok = " ".join(words)
                key = fold(tok)
                if key in known or len(key) < 3:
                    continue
                freq[key] += 1
                srcs[key].add((r["source_type"], r["source_id"]))
                if key not in first:
                    first[key] = {"name": tok, "source_type": r["source_type"], "source_id": r["source_id"],
                                  "source_title": r["source_title"],
                                  "quote": _sentence_around(content, m.start(), m.end())}
    ranked = []
    for key, n in freq.items():
        ns = len(srcs[key])
        if ns >= min_sources and n >= 2:
            ranked.append((ns * math.log(1 + n), key))
    ranked.sort(reverse=True)
    out = []
    for _, key in ranked[:limit]:
        c = first[key]
        out.append({**c, "count": freq[key], "sources": len(srcs[key])})
    return out


def accept_candidates(items: List[Dict[str, Any]]) -> Dict[str, int]:
    """Tạo thuật ngữ NHÁP (chưa có định nghĩa, chưa duyệt) từ ứng viên, kèm dẫn chứng đã kiểm."""
    created = skipped = 0
    for it in items:
        try:
            t = create_term(it.get("name", ""), "concept", "", [])
        except OntologyError:
            skipped += 1
            continue
        if it.get("quote") and it.get("source_type") and it.get("source_id") is not None:
            try:
                add_evidence(t["id"], it["source_type"], int(it["source_id"]), it["quote"])
            except OntologyError:
                pass
        created += 1
    return {"created": created, "skipped": skipped}


# --------------------------------------------------------------------------- xuất / nhập / đồ thị

def export_all() -> Dict[str, Any]:
    terms = []
    for t in list_terms():
        full = get_term(t["id"])
        terms.append({
            "name": full["name"], "kind": full["kind"], "definition": full["definition"], "status": full["status"],
            "aliases": full["aliases"],
            "relations": [{"to": r["other_name"], "kind": r["kind"], "note": r["note"]}
                          for r in full["relations"] if r["direction"] == "out"],
            "evidence": [{"source_type": e["source_type"], "source_id": e["source_id"], "source_title": e["source_title"],
                          "quote": e["quote"], "verified": bool(e["verified"])} for e in full["evidence"]],
        })
    return {"format": "second-brain-ontology", "version": 1, "exported_at": _now(), "terms": terms}


def export_markdown() -> str:
    data = export_all()
    lines = ["# Ontology (thuật ngữ đã duyệt)", ""]
    for t in data["terms"]:
        if t["status"] != "approved":
            continue
        alias = f" — còn gọi: {', '.join(t['aliases'])}" if t["aliases"] else ""
        lines.append(f"## {t['name']} ({t['kind']}){alias}")
        lines.append(t["definition"])
        for r in t["relations"]:
            lines.append(f"- {r['kind']} → {r['to']}")
        lines.append("")
    return "\n".join(lines)


def import_all(data: Dict[str, Any]) -> Dict[str, int]:
    """Gộp (merge) từ file xuất: thuật ngữ trùng tên thì bỏ qua. Mọi thuật ngữ nhập vào đều ở trạng thái NHÁP."""
    if not isinstance(data, dict) or data.get("format") != "second-brain-ontology":
        raise OntologyError("File không đúng định dạng second-brain-ontology")
    created = skipped = 0
    pending_rel = []
    for t in data.get("terms", []):
        try:
            create_term(t.get("name", ""), t.get("kind", "concept") if t.get("kind") in KINDS else "concept",
                        t.get("definition", ""), t.get("aliases", []))
            created += 1
        except OntologyError:
            skipped += 1
        for r in t.get("relations", []):
            pending_rel.append((t.get("name", ""), r))
    ids = {fold(t["name"]): t["id"] for t in list_terms()}
    rels = 0
    for src, r in pending_rel:
        a, b = ids.get(fold(src)), ids.get(fold(r.get("to", "")))
        if a and b:
            try:
                add_relation(a, b, r.get("kind", "related_to"), r.get("note", ""))
                rels += 1
            except OntologyError:
                pass
    return {"created": created, "skipped": skipped, "relations": rels}


def graph() -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        nodes = [dict(r) for r in conn.execute("SELECT id, name, kind, status FROM ontology_terms ORDER BY name COLLATE NOCASE")]
        edges = [dict(r) for r in conn.execute("SELECT id, from_id, to_id, kind FROM ontology_relations")]
        return {"nodes": nodes, "edges": edges}
    finally:
        conn.close()
