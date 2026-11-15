from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from brain_app.models import SearchResult
from brain_app.rag.embeddings import embedding_service, EmbeddingError
from brain_app.rag.vector_store import vector_store

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=List[SearchResult])
async def search(
    response: Response,
    q: str = Query(..., min_length=1),
    limit: int = 10,
    source_type: Optional[str] = None
):
    """Hybrid search: semantic (embeddings) + keyword (FTS5), fused with RRF.

    If embeddings are unavailable the search still works by keyword and the reason is returned in the
    `X-Search-Warning` header (URL-encoded) instead of failing.
    """
    if not q.strip():
        return []

    query_vector = None
    try:
        query_vector = await embedding_service.embed_query(q)
    except EmbeddingError as e:
        response.headers["X-Search-Warning"] = quote(str(e))

    results = vector_store.hybrid_search(
        q, query_vector, model_tag=embedding_service.active_tag(), top_k=limit, source_type=source_type)

    return [
        SearchResult(
            id=r["id"],
            source_type=r["source_type"],
            source_id=r["source_id"],
            source_title=r["source_title"],
            content=r["content"],
            score=r["score"],
            metadata=r["metadata"],
            match=r.get("match", "semantic"),
        ) for r in results
    ]
