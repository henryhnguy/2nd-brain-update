"""Background job that (re-)embeds chunks whose vector does not match the active embedding model."""
import asyncio
import json
import time
from typing import Any, Dict, Optional

from brain_app.database import get_db_connection
from brain_app.rag.embeddings import EmbeddingError, embedding_service


class ReindexManager:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self.state: Dict[str, Any] = self._idle_state()

    @staticmethod
    def _idle_state() -> Dict[str, Any]:
        return {"running": False, "total": 0, "done": 0, "error": None,
                "tag": None, "started_at": None, "finished_at": None}

    def snapshot(self) -> Dict[str, Any]:
        return dict(self.state)

    def start(self, force_all: bool = False) -> bool:
        """Schedule a run. Returns False if one is already running."""
        if self._task and not self._task.done():
            return False
        self._task = asyncio.get_running_loop().create_task(self.run(force_all))
        return True

    async def wait(self):
        if self._task:
            await self._task

    async def run(self, force_all: bool = False):
        self.state = self._idle_state()
        self.state.update(running=True, started_at=time.time())
        try:
            tag = embedding_service.active_tag()
            self.state["tag"] = tag
            conn = get_db_connection()
            if force_all:
                rows = conn.execute("SELECT id, content FROM chunks ORDER BY id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, content FROM chunks WHERE embedding_model IS NULL OR embedding_model != ? ORDER BY id",
                    (tag,)).fetchall()
            conn.close()
            self.state["total"] = len(rows)

            step = 50 if embedding_service.resolved_provider() == "gemini" else 16
            for i in range(0, len(rows), step):
                batch = rows[i:i + step]
                vecs = await embedding_service.embed_documents([r["content"] for r in batch])
                conn = get_db_connection()
                conn.executemany(
                    "UPDATE chunks SET embedding = ?, embedding_model = ? WHERE id = ?",
                    [(json.dumps(v), tag, r["id"]) for r, v in zip(batch, vecs)])
                conn.commit()
                conn.close()
                self.state["done"] = min(i + step, len(rows))
        except EmbeddingError as e:
            self.state["error"] = str(e)
        except Exception as e:  # never let a background job crash the server
            self.state["error"] = f"Lỗi không mong đợi: {e}"
        finally:
            self.state.update(running=False, finished_at=time.time())


reindex_manager = ReindexManager()
