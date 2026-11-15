"""Deterministic checks on generated text (no LLM): citation coverage and SOP completeness."""
import re
from typing import Any, Dict, List, Set

CITE_RE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
PLACEHOLDER = "CẦN BỔ SUNG"
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}", re.MULTILINE)


def cited_numbers(text: str) -> Set[int]:
    out: Set[int] = set()
    for m in CITE_RE.finditer(text or ""):
        out.update(int(x) for x in re.split(r"[,;]\s*", m.group(1)))
    return out


def _paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def check_citations(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Flag long paragraphs without any [n] and citation numbers that are not in the source list."""
    valid = {s["n"] for s in doc.get("sources", [])}
    uncited, invalid, total, cited = [], set(), 0, 0
    titles = {o["id"]: o["title"] for o in doc.get("outline", [])}
    for sid, sec in doc.get("sections", {}).items():
        content = sec.get("content") or ""
        invalid |= {n for n in cited_numbers(content) if n not in valid}
        for p in _paragraphs(content):
            if p.startswith("#") or p.startswith("|") or p.startswith("```") or len(p) < 80:
                continue
            if "kiến thức chung" in p.lower() or PLACEHOLDER in p:
                continue
            total += 1
            if cited_numbers(p):
                cited += 1
            else:
                uncited.append({"section": titles.get(sid, sid), "excerpt": p[:160]})
    return {
        "total_paragraphs": total,
        "cited_paragraphs": cited,
        "coverage": round(cited / total, 2) if total else 1.0,
        "uncited_paragraphs": uncited,
        "invalid_citations": sorted(invalid),
    }


def sop_checks(doc: Dict[str, Any], procedure_title: str) -> List[Dict[str, str]]:
    """Completeness findings for an SOP that do not need an LLM."""
    findings: List[Dict[str, str]] = []
    for o in doc.get("outline", []):
        sec = doc.get("sections", {}).get(o["id"], {})
        content = sec.get("content") or ""
        if not content.strip():
            findings.append({"severity": "high", "section": o["title"], "kind": "missing",
                             "issue": "Mục này chưa được viết.", "suggestion": "Viết mục này trước khi phát hành."})
            continue
        n_ph = content.count(PLACEHOLDER)
        if n_ph:
            findings.append({"severity": "high", "section": o["title"], "kind": "placeholder",
                             "issue": f"Còn {n_ph} chỗ thiếu thông tin ({PLACEHOLDER}).",
                             "suggestion": "Điền thông tin thật (hoặc trả lời câu hỏi bổ sung) rồi viết lại mục này."})
        if o["title"] == procedure_title and not _TABLE_SEP.search(content):
            findings.append({"severity": "high", "section": o["title"], "kind": "no_table",
                             "issue": "Chưa có bảng các bước (Bước | Hoạt động | Người thực hiện | Tiêu chí đạt).",
                             "suggestion": "Viết lại mục này theo dạng bảng."})
    open_q = [q for q in doc.get("questions", []) if not (q.get("answer") or "").strip()]
    if open_q:
        findings.append({"severity": "medium", "section": "Câu hỏi bổ sung", "kind": "unanswered",
                         "issue": f"{len(open_q)} câu hỏi bổ sung chưa được trả lời.",
                         "suggestion": "Trả lời rồi viết lại các mục liên quan để SOP chính xác hơn."})
    return findings
