import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_app import database  # noqa: E402
from brain_app.rag import embeddings  # noqa: E402
from brain_app.rag.embeddings import embedding_service  # noqa: E402
from brain_app.rag.reindex import reindex_manager  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Fresh, isolated SQLite DB per test."""
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    database.init_db()
    embedding_service._transport = None
    embedding_service._local_models.clear()
    reindex_manager.state = reindex_manager._idle_state()

    async def no_sleep(_):
        return None
    monkeypatch.setattr(embeddings, "_sleep", no_sleep)
    yield tmp_path
    embedding_service._transport = None


def set_setting(key: str, value: str):
    conn = database.get_db_connection()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()
