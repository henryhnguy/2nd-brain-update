import os
import json
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from brain_app.database import init_db, get_db_connection
from brain_app.routers import notes, documents, chat, search, settings, studio, ontology
from brain_app.rag.rag_service import rag_service
from brain_app.rag.embeddings import embedding_service
from brain_app.rag.vector_store import vector_store
from brain_app.rag.reindex import reindex_manager

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if not FRONTEND_DIST.exists():
    env_dist = os.getenv("FRONTEND_DIST")
    if env_dist and Path(env_dist).exists():
        FRONTEND_DIST = Path(env_dist)
    elif Path("/app/frontend/dist").exists():
        FRONTEND_DIST = Path("/app/frontend/dist")


async def _startup_indexing():
    """Index seed notes and embed any pending/stale chunks without blocking server start-up."""
    try:
        conn = get_db_connection()
        chunk_count = conn.execute("SELECT COUNT(*) as cnt FROM chunks").fetchone()["cnt"]
        if chunk_count == 0:
            seed_rows = conn.execute("SELECT * FROM notes").fetchall()
            conn.close()
            for r in seed_rows:
                tags = json.loads(r["tags"]) if r["tags"] else []
                await rag_service.index_note(r["id"], r["title"], r["content"], r["category"], tags)
        else:
            conn.close()
        tag = embedding_service.active_tag()
        if vector_store.stats(tag)["stale"] > 0:
            reindex_manager.start()
    except Exception as e:
        print(f"[startup] indexing skipped: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_startup_indexing())
    yield
    task.cancel()


app = FastAPI(
    title="Second Brain AI API",
    description="Personal Knowledge Management & RAG Copilot",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(notes.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(search.router)
app.include_router(settings.router)
app.include_router(studio.router)
app.include_router(ontology.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "Second Brain AI"}


# Serve static production frontend if built
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # Don't intercept API routes
        if full_path.startswith("api"):
            return {"error": "API route not found"}
        target_file = FRONTEND_DIST / full_path
        if target_file.is_file():
            return FileResponse(str(target_file))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
