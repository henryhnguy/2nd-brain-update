import json
import re
import sqlite3
from typing import List, Dict, Any, Optional, Set, Tuple
import numpy as np
from brain_app.database import get_db_connection


_STOPWORDS = {
    "và", "của", "là", "gì", "có", "không", "những", "các", "cho", "trong", "một", "được", "với", "này",
    "khi", "thì", "để", "như", "the", "and", "for", "what", "how", "is", "are", "of", "to", "in", "a",
}


def build_fts_query(text: str) -> str:
    """Safe FTS5 query: quoted OR-terms, prefix match for longer words. '' if nothing usable."""
    words = re.findall(r"\w+", (text or "").lower(), re.UNICODE)
    terms = [w for w in words if len(w) >= 2 and w not in _STOPWORDS] or words
    seen, uniq = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return " OR ".join(f'"{t}"*' if len(t) >= 4 else f'"{t}"' for t in uniq[:12])


class VectorStore:
    """SQLite-backed vector store. Vectors are only compared within the same embedding_model tag."""

    def add_chunks(self, chunks: List[Dict[str, Any]]):
        """
        Each chunk: source_type, source_id, source_title, chunk_index, content,
        embedding (list, may be empty = pending), embedding_model (tag, '' = pending),
        metadata (dict), created_at
        """
        if not chunks:
            return
        conn = get_db_connection()
        cursor = conn.cursor()
        for c in chunks:
            cursor.execute("""
                INSERT INTO chunks (
                    source_type, source_id, source_title, chunk_index, content,
                    embedding, embedding_model, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                c["source_type"], c["source_id"], c["source_title"], c["chunk_index"], c["content"],
                json.dumps(c.get("embedding") or []),
                c.get("embedding_model", "") if c.get("embedding") else "",
                json.dumps(c.get("metadata", {})),
                c["created_at"],
            ))
        conn.commit()
        conn.close()

    def delete_by_source(self, source_type: str, source_id: int):
        conn = get_db_connection()
        conn.execute("DELETE FROM chunks WHERE source_type = ? AND source_id = ?", (source_type, source_id))
        conn.commit()
        conn.close()

    def _vector_rank(self, query_vector, model_tag, source_type=None) -> List[Dict[str, Any]]:
        """Every chunk embedded with `model_tag`, scored by cosine similarity, best first."""
        conn = get_db_connection()
        sql = ("SELECT id, source_type, source_id, source_title, chunk_index, content, embedding, metadata "
               "FROM chunks WHERE embedding_model = ?")
        params: List[Any] = [model_tag]
        if source_type:
            sql += " AND source_type = ?"
            params.append(source_type)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        if not rows:
            return []

        q = np.asarray(query_vector, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn > 1e-9:
            q = q / qn

        keep, vecs = [], []
        for r in rows:
            try:
                v = np.asarray(json.loads(r["embedding"]), dtype=np.float32)
            except Exception:
                continue
            if v.shape != q.shape:
                continue
            keep.append(r)
            vecs.append(v)
        if not vecs:
            return []

        mat = np.stack(vecs)
        norms = np.linalg.norm(mat, axis=1)
        norms[norms < 1e-9] = 1.0
        scores = (mat / norms[:, None]) @ q
        order = np.argsort(-scores)
        return [self._row_to_result(keep[int(i)], float(scores[int(i)])) for i in order]

    @staticmethod
    def _row_to_result(r, score: float) -> Dict[str, Any]:
        return {
            "id": r["id"],
            "source_type": r["source_type"],
            "source_id": r["source_id"],
            "source_title": r["source_title"],
            "chunk_index": r["chunk_index"],
            "content": r["content"],
            "score": round(score, 4),
            "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
        }

    def similarity_search(
        self,
        query_vector: List[float],
        model_tag: str,
        top_k: int = 5,
        source_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Cosine similarity over chunks embedded with `model_tag` only."""
        return self._vector_rank(query_vector, model_tag, source_type)[:top_k]

    def keyword_search(self, query_text: str, top_k: int = 20, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """BM25 keyword search (FTS5). Works regardless of embeddings. Title counts double."""
        fts_q = build_fts_query(query_text)
        if not fts_q:
            return []
        sql = ("SELECT c.id, c.source_type, c.source_id, c.source_title, c.chunk_index, c.content, c.metadata "
               "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid WHERE chunks_fts MATCH ?")
        params: List[Any] = [fts_q]
        if source_type:
            sql += " AND c.source_type = ?"
            params.append(source_type)
        sql += " ORDER BY bm25(chunks_fts, 1.0, 2.0) LIMIT ?"
        params.append(top_k)
        conn = get_db_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:  # no FTS5 in this SQLite build, or malformed query
            rows = []
        finally:
            conn.close()
        return [self._row_to_result(r, 0.0) for r in rows]

    def hybrid_search(
        self,
        query_text: str,
        query_vector: Optional[List[float]],
        model_tag: str,
        top_k: int = 5,
        source_type: Optional[str] = None,
        pool: int = 30,
        allowed: Optional[Set[Tuple[str, int]]] = None,
    ) -> List[Dict[str, Any]]:
        """Reciprocal Rank Fusion of semantic and keyword rankings.

        `score` stays the cosine similarity (0.0 when the chunk has no vector for the active model),
        `match` says where it came from: 'semantic', 'keyword' or 'both'.
        With query_vector=None (embedding unavailable) it degrades to keyword-only.
        """
        vec_all = self._vector_rank(query_vector, model_tag, source_type) if query_vector else []
        kw = self.keyword_search(query_text, pool * 4 if allowed is not None else pool, source_type)
        if allowed is not None:  # restrict to a user-chosen scope (set of (source_type, source_id))
            vec_all = [r for r in vec_all if (r["source_type"], r["source_id"]) in allowed]
            kw = [r for r in kw if (r["source_type"], r["source_id"]) in allowed][:pool]
        vec_rank = {r["id"]: i for i, r in enumerate(vec_all[:pool])}
        kw_rank = {r["id"]: i for i, r in enumerate(kw)}
        cosine = {r["id"]: r["score"] for r in vec_all}
        by_id = {r["id"]: r for r in kw}
        by_id.update({r["id"]: r for r in vec_all[:pool]})

        K = 60
        fused = {}
        for cid in set(vec_rank) | set(kw_rank):
            fused[cid] = (1 / (K + vec_rank[cid] + 1) if cid in vec_rank else 0.0) + \
                         (1 / (K + kw_rank[cid] + 1) if cid in kw_rank else 0.0)

        out = []
        for cid in sorted(fused, key=lambda c: -fused[c])[:top_k]:
            r = dict(by_id[cid])
            r["score"] = round(cosine.get(cid, 0.0), 4)
            r["match"] = "both" if cid in vec_rank and cid in kw_rank else ("semantic" if cid in vec_rank else "keyword")
            out.append(r)
        return out

    def stats(self, active_tag: str) -> Dict[str, Any]:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT COALESCE(NULLIF(embedding_model, ''), 'pending') AS tag, COUNT(*) AS n "
            "FROM chunks GROUP BY tag").fetchall()
        conn.close()
        by_model = {r["tag"]: r["n"] for r in rows}
        total = sum(by_model.values())
        current = by_model.get(active_tag, 0)
        return {"total": total, "current": current, "stale": total - current, "by_model": by_model}


vector_store = VectorStore()
