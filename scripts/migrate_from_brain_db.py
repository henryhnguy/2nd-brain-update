"""Chuyển dữ liệu từ app Second Brain (Next.js, file brain.db) sang 2nd-brain-update (FastAPI).

Chỉ ĐỌC brain.db (mở chế độ read-only, không sửa gì). Ghi vào bản mới qua API của nó, nên
chia đoạn, FTS và embedding do bản mới tự làm.

Chuyển:
  - Ghi chú (source_kind = 'note'): nội dung Markdown trong note_bodies -> Ghi chú ở bản mới
  - Tài liệu còn lại: ghép các đoạn (chunks) theo thứ tự thành văn bản -> Kho tài liệu (.md)
  - Ghi chú giữ thẻ (tags) và category PARA suy ra từ thư mục nguồn (03_Projects -> Projects,
    99_Archive -> Archives, ...), không có thì dùng --default-category. Kho tài liệu của bản mới không
    có category/thẻ riêng, nên với tài liệu, script ghi thông tin này vào đầu văn bản để vẫn tìm được
Không chuyển (bản mới chưa có tính năng tương ứng): đồ thị tri thức (entities/edges), mind map
trong bảng artifacts, plays, connectors, lịch sử chat. Dữ liệu đó vẫn còn nguyên trong brain.db.

Lưu ý: tài liệu gốc (PDF, DOCX, XLSX) được dựng lại từ văn bản đã trích xuất, nên mất định dạng và
hình ảnh. Muốn giữ file gốc, dùng import_folder.py trên thư mục Drive.

Ví dụ:
  python scripts/migrate_from_brain_db.py --db "C:/.../repo/data/brain.db" --new-api http://127.0.0.1:8001 --dry-run
  python scripts/migrate_from_brain_db.py --db "C:/.../repo/data/brain.db" --new-api http://127.0.0.1:8001
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import httpx

PARA = {
    "projects": "Projects", "project": "Projects", "du an": "Projects",
    "areas": "Areas", "area": "Areas", "linh vuc": "Areas",
    "resources": "Resources", "resource": "Resources", "tai nguyen": "Resources",
    "archives": "Archives", "archive": "Archives", "luu tru": "Archives",
}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"^[\d\s._-]+", "", text).strip()


def category_for(doc: sqlite3.Row, default: str) -> str:
    candidates = [doc["source_id"] or ""]
    candidates += re.split(r"[\\/]+", doc["path"] or "")
    for c in candidates:
        for part in re.split(r"[\\/]+", c):
            key = fold(part)
            if key in PARA:
                return PARA[key]
    return default


def safe_name(title: str, doc_id: str) -> str:
    base = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", title or "").strip()[:80] or "document"
    return f"{base} [{hashlib.sha1(doc_id.encode()).hexdigest()[:6]}].md"


def main() -> int:
    for _s in (sys.stdout, sys.stderr):  # Windows cp1252 console: không để ký tự lạ làm script dừng
        try:
            _s.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="Đường dẫn file brain.db")
    ap.add_argument("--new-api", required=True, help="Địa chỉ app bản mới, vd http://127.0.0.1:8001")
    ap.add_argument("--default-category", default="Resources", choices=["Projects", "Areas", "Resources", "Archives"])
    ap.add_argument("--exclude-source", action="append", default=[], metavar="TÊN",
                    help="Bỏ qua tài liệu có source_id hoặc đường dẫn chứa tên này, vd 99_Archive")
    ap.add_argument("--limit", type=int, default=0, help="Chỉ chuyển N mục đầu (để thử)")
    ap.add_argument("--only", choices=["notes", "docs"], help="Chỉ chuyển ghi chú hoặc chỉ chuyển tài liệu")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        print(f"Không thấy file: {db_path}")
        return 2
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    docs = con.execute(
        "SELECT * FROM documents WHERE deleted_at IS NULL AND COALESCE(status,'indexed') != 'deleted' "
        "ORDER BY created_at").fetchall()
    tags: dict[str, list[str]] = {}
    for r in con.execute("SELECT dt.document_id, t.name FROM document_tags dt JOIN tags t ON t.id = dt.tag_id"):
        tags.setdefault(r["document_id"], []).append(r["name"])
    bodies = {r["document_id"]: r["markdown"] for r in con.execute("SELECT document_id, markdown FROM note_bodies")}
    excl = [fold(e) for e in args.exclude_source]

    client = None
    have_notes: set[tuple[str, str]] = set()
    have_docs: set[str] = set()
    if not args.dry_run:
        client = httpx.Client(base_url=args.new_api, timeout=300)
        try:
            have_notes = {(n["title"].strip().lower(), n["category"]) for n in client.get("/api/notes").json()}
            have_docs = {d["filename"].lower() for d in client.get("/api/documents").json()}
        except Exception as e:
            print(f"Không kết nối được bản mới tại {args.new_api}: {e}")
            return 2

    stats = dict(note=0, doc=0, skip=0, empty=0, error=0)
    done = 0
    for d in docs:
        if args.limit and done >= args.limit:
            break
        hay = fold(" ".join([d["source_id"] or "", d["path"] or ""]))
        if any(e and e in hay for e in excl):
            stats["skip"] += 1
            continue
        title = (d["title"] or "Không tiêu đề").strip()
        cat = category_for(d, args.default_category)
        tg = [t[:60] for t in tags.get(d["id"], [])][:12]

        if d["source_kind"] == "note" and d["id"] in bodies:
            text = bodies[d["id"]]
            kind = "note"
        else:
            parts = [r["text"] for r in con.execute(
                "SELECT text FROM chunks WHERE document_id = ? ORDER BY ord", (d["id"],))]
            text = "\n\n".join(p for p in parts if p)
            kind = "doc"
        if args.only and (args.only == "notes") != (kind == "note"):
            continue
        if not (text or "").strip():
            stats["empty"] += 1
            continue

        done += 1
        if kind == "note":
            print(f"[note] {cat:<9} {title[:70]}")
            if client:
                if (title.lower(), cat) in have_notes:
                    stats["skip"] += 1
                    continue
                try:
                    r = client.post("/api/notes", json={
                        "title": title[:200], "content": text, "category": cat,
                        "tags": tg, "pinned": 1 if d["pinned"] else 0})
                    r.raise_for_status()
                except Exception as e:
                    stats["error"] += 1
                    print(f"[LỖI ] {title[:50]}: {e}")
                    continue
            stats["note"] += 1
        else:
            name = safe_name(title, d["id"])
            meta_line = f"Nhóm: {cat}" + (f" | Thẻ: {', '.join(tg)}" if tg else "")
            header = f"# {title}\n\n{meta_line}\n\n" + (f"Nguồn: {d['path']}\n\n" if d["path"] else "")
            print(f"[doc ] {name[:80]}")
            if client:
                if name.lower() in have_docs:
                    stats["skip"] += 1
                    continue
                try:
                    r = client.post("/api/documents/upload",
                                    files={"file": (name, (header + text).encode("utf-8"), "text/markdown")})
                    r.raise_for_status()
                    body = r.json()
                    if not body.get("success"):
                        raise RuntimeError(body.get("error", "upload thất bại"))
                except Exception as e:
                    stats["error"] += 1
                    print(f"[LỖI ] {name[:50]}: {e}")
                    continue
            stats["doc"] += 1

    print("\n=== Kết quả" + (" (chạy thử, chưa gửi gì)" if args.dry_run else "") + " ===")
    print(f"Ghi chú: {stats['note']} | Tài liệu: {stats['doc']} | Bỏ qua/đã có: {stats['skip']} | "
          f"Rỗng: {stats['empty']} | Lỗi: {stats['error']} (brain.db có {len(docs)} tài liệu)")
    return 1 if stats["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
