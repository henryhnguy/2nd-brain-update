import os
from fastapi import APIRouter, HTTPException
from brain_app.database import get_db_connection
from brain_app.models import SettingsUpdate
from brain_app.rag.embeddings import embedding_service, PROVIDERS, LOCAL_MODELS
from brain_app.rag.rag_service import rag_service
from brain_app.rag.vector_store import vector_store
from brain_app.rag.reindex import reindex_manager
from brain_app.rag.model_catalog import (
    GEMINI_FALLBACK, OPENROUTER_FALLBACK, DEFAULT_GEMINI_CHAT_MODEL, list_models,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Static fallbacks (the UI loads live lists from /api/settings/models)
POPULAR_OPENROUTER_MODELS = [dict(m, provider="openrouter") for m in OPENROUTER_FALLBACK]
GEMINI_MODELS = [dict(m, provider="gemini") for m in GEMINI_FALLBACK]


def embedding_block():
    status = embedding_service.status()
    return {
        **status,
        "chunks": vector_store.stats(status["active_tag"]),
        "reindex": reindex_manager.snapshot(),
    }


@router.get("")
def get_settings():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    settings_dict = {r["key"]: r["value"] for r in rows}

    # Mask Gemini API key
    gemini_key = settings_dict.get("gemini_api_key", "")
    gemini_masked = ""
    if gemini_key:
        gemini_masked = gemini_key[:4] + "*" * (len(gemini_key) - 8) + gemini_key[-4:] if len(gemini_key) > 8 else "****"

    # Mask OpenRouter API key
    or_key = settings_dict.get("openrouter_api_key", "")
    or_masked = ""
    if or_key:
        or_masked = or_key[:4] + "*" * (len(or_key) - 8) + or_key[-4:] if len(or_key) > 8 else "****"

    # Count statistics
    cursor.execute("SELECT COUNT(*) as cnt FROM notes")
    total_notes = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(*) as cnt FROM documents")
    total_docs = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(*) as cnt FROM chunks")
    total_chunks = cursor.fetchone()["cnt"]

    conn.close()

    llm_provider = settings_dict.get("llm_provider", "gemini")
    gemini_model = settings_dict.get("gemini_model", settings_dict.get("model_name", DEFAULT_GEMINI_CHAT_MODEL))
    openrouter_model = settings_dict.get("openrouter_model", "deepseek/deepseek-chat")

    return {
        "embedding": embedding_block(),
        "llm_provider": llm_provider,
        "gemini_api_key_configured": bool(gemini_key and len(gemini_key) > 10),
        "gemini_api_key_masked": gemini_masked,
        "gemini_model": gemini_model,
        "model_name": gemini_model, # backward compatibility
        "openrouter_api_key_configured": bool(or_key and len(or_key) > 5),
        "openrouter_api_key_masked": or_masked,
        "openrouter_model": openrouter_model,
        "available_models": {
            "gemini": GEMINI_MODELS,
            "openrouter": POPULAR_OPENROUTER_MODELS
        },
        "stats": {
            "total_notes": total_notes,
            "total_documents": total_docs,
            "total_chunks": total_chunks
        }
    }


@router.post("")
async def update_settings(data: SettingsUpdate):
    if data.embedding_provider is not None and data.embedding_provider.strip().lower() not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"embedding_provider phải thuộc {list(PROVIDERS)}")
    if data.embedding_local_model is not None and data.embedding_local_model not in {m["id"] for m in LOCAL_MODELS}:
        raise HTTPException(status_code=400, detail="embedding_local_model không được hỗ trợ")

    tag_before = embedding_service.active_tag()
    conn = get_db_connection()
    cursor = conn.cursor()

    if data.llm_provider is not None:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('llm_provider', ?)", (data.llm_provider.strip().lower(),))

    if data.gemini_api_key is not None:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gemini_api_key', ?)", (data.gemini_api_key.strip(),))
        embedding_service.update_api_key(data.gemini_api_key.strip())

    if data.openrouter_api_key is not None:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('openrouter_api_key', ?)", (data.openrouter_api_key.strip(),))

    if data.gemini_model is not None:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gemini_model', ?)", (data.gemini_model.strip(),))
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('model_name', ?)", (data.gemini_model.strip(),))

    if data.openrouter_model is not None:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('openrouter_model', ?)", (data.openrouter_model.strip(),))

    if data.model_name is not None and data.gemini_model is None:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('model_name', ?)", (data.model_name.strip(),))
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gemini_model', ?)", (data.model_name.strip(),))

    if data.embedding_provider is not None:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('embedding_provider', ?)", (data.embedding_provider.strip().lower(),))
    if data.embedding_gemini_model is not None and data.embedding_gemini_model.strip():
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('embedding_gemini_model', ?)", (data.embedding_gemini_model.strip(),))
    if data.embedding_local_model is not None:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('embedding_local_model', ?)", (data.embedding_local_model,))

    conn.commit()
    conn.close()

    # Embedding config changed -> re-embed stale chunks in the background
    reindex_started = False
    if embedding_service.active_tag() != tag_before:
        reindex_started = reindex_manager.start()

    return {"success": True, "message": "Đã lưu cấu hình cài đặt", "reindex_started": reindex_started}


@router.get("/models")
async def get_models(provider: str = "gemini", refresh: bool = False):
    """Live chat-model list for a provider (falls back to a static list when offline)."""
    try:
        return await list_models(provider, refresh)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/embedding/status")
def embedding_status():
    return embedding_block()


@router.post("/embedding/test")
async def embedding_test():
    """Embed one sentence with the active provider (first local use downloads the model)."""
    return await embedding_service.probe()


@router.post("/embedding/reindex")
async def embedding_reindex(all: bool = False):
    started = reindex_manager.start(force_all=all)
    return {"started": started, **embedding_block()}
