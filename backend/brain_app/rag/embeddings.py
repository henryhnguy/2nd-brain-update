"""Embedding service with two real providers plus an explicit weak fallback.

Providers
---------
gemini : Google Gemini embedding API (batchEmbedContents). Needs an API key.
local  : multilingual model run on this machine through `fastembed` (ONNX).
hash   : legacy hashed bag-of-words. Offline but NOT semantic. Only used when
         chosen explicitly or when provider="auto" and no Gemini key exists.

Design rules
------------
* No silent fallback: if the chosen provider fails, EmbeddingError is raised
  with a human-readable message (callers decide how to surface it).
* Every stored vector is tagged with `active_tag()` so vectors from different
  models are never compared with each other.
"""
import asyncio
import hashlib
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import numpy as np

from brain_app.database import DB_DIR, get_db_connection

GEMINI_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")  # overridable for proxies/tests
DEFAULT_GEMINI_MODEL = "gemini-embedding-001"
GEMINI_DIM = 768  # we request 768 dims (smaller storage, plenty for personal KBs)
GEMINI_BATCH = 50
GEMINI_MAX_CHARS = 8000

DEFAULT_LOCAL_MODEL = "intfloat/multilingual-e5-large"
LOCAL_CACHE_DIR = DB_DIR / "models"

HASH_DIM = 384
LOCAL_RETRY_COOLDOWN = 120  # seconds before retrying a failed local model download

PROVIDERS = ("auto", "gemini", "local", "hash")

LOCAL_MODELS: List[Dict[str, Any]] = [
    {
        "id": "intfloat/multilingual-e5-large",
        "name": "Multilingual E5 Large",
        "dim": 1024,
        "size_gb": 2.24,
        "prefixed": True,  # needs "query: " / "passage: " prefixes
        "desc": "Chất lượng hỏi–đáp tốt nhất, ~100 ngôn ngữ (có tiếng Việt). Nặng nhất.",
    },
    {
        "id": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "name": "Multilingual MPNet",
        "dim": 768,
        "size_gb": 1.0,
        "prefixed": False,
        "desc": "Cân bằng dung lượng và chất lượng. Tối ưu cho độ giống câu hơn là hỏi–đáp.",
    },
    {
        "id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "name": "Multilingual MiniLM",
        "dim": 384,
        "size_gb": 0.22,
        "prefixed": False,
        "desc": "Nhẹ nhất, hợp máy yếu. Chỉ đọc khoảng 128 token đầu mỗi đoạn.",
    },
]
_LOCAL_BY_ID = {m["id"]: m for m in LOCAL_MODELS}


class EmbeddingError(Exception):
    """Raised when the selected embedding provider cannot produce vectors."""


async def _sleep(seconds: float):  # indirection so tests can skip real waiting
    await asyncio.sleep(seconds)


def _normalize(vec) -> List[float]:
    arr = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 1e-9:
        arr = arr / norm
    return arr.tolist()


def fastembed_available() -> bool:
    try:
        import fastembed  # noqa: F401
        return True
    except Exception:
        return False


class EmbeddingService:
    def __init__(self):
        self._local_models: Dict[str, Any] = {}
        self._local_lock = threading.Lock()
        self._local_failures: Dict[str, tuple] = {}  # model_id -> (monotonic time, message)
        self._transport: Optional[httpx.AsyncBaseTransport] = None  # tests inject a mock here

    # ------------------------------------------------------------------ config
    @staticmethod
    def _get_setting(key: str, default: str = "") -> str:
        try:
            conn = get_db_connection()
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            conn.close()
            return row["value"] if row and row["value"] is not None else default
        except Exception:
            return default

    def reload(self):
        """Settings are read on demand, so there is nothing to refresh. Kept for callers."""

    def update_api_key(self, api_key: str):  # backward compatible shim
        self.reload()

    def gemini_key(self) -> str:
        key = self._get_setting("gemini_api_key", "") or os.getenv("GEMINI_API_KEY", "")
        return key.strip() if key and len(key.strip()) > 10 else ""

    def gemini_model(self) -> str:
        m = self._get_setting("embedding_gemini_model", "") or DEFAULT_GEMINI_MODEL
        return m.strip().replace("models/", "")

    def local_model(self) -> str:
        return self._get_setting("embedding_local_model", "") or DEFAULT_LOCAL_MODEL

    def configured_provider(self) -> str:
        p = (self._get_setting("embedding_provider", "auto") or "auto").lower()
        return p if p in PROVIDERS else "auto"

    def resolved_provider(self) -> str:
        p = self.configured_provider()
        if p != "auto":
            return p
        return "gemini" if self.gemini_key() else "hash"

    def active_tag(self) -> str:
        p = self.resolved_provider()
        if p == "gemini":
            return f"gemini:{self.gemini_model()}:{GEMINI_DIM}"
        if p == "local":
            return f"local:{self.local_model()}"
        return f"hash:{HASH_DIM}"

    def status(self) -> Dict[str, Any]:
        p = self.resolved_provider()
        local_id = self.local_model()
        info = _LOCAL_BY_ID.get(local_id, {})
        warning = ""
        if p == "hash":
            warning = ("Đang dùng embedding dự phòng (băm từ khóa), KHÔNG hiểu ngữ nghĩa. "
                       "Hãy chọn Gemini hoặc Local để tìm kiếm tốt hơn.")
        elif p == "gemini" and not self.gemini_key():
            warning = "Chưa có Gemini API Key."
        elif p == "local" and not fastembed_available():
            warning = "Chưa cài fastembed. Chạy: pip install -r backend/requirements-local.txt"
        return {
            "configured_provider": self.configured_provider(),
            "resolved_provider": p,
            "active_tag": self.active_tag(),
            "quality": "weak" if p == "hash" else "semantic",
            "warning": warning,
            "gemini_key_configured": bool(self.gemini_key()),
            "gemini_model": self.gemini_model(),
            "gemini_dim": GEMINI_DIM,
            "local_available": fastembed_available(),
            "local_model": local_id,
            "local_model_loaded": local_id in self._local_models,
            "local_model_size_gb": info.get("size_gb"),
            "local_models": LOCAL_MODELS,
        }

    # -------------------------------------------------------------- public API
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return await self._embed(texts, is_query=False)

    async def embed_query(self, text: str) -> List[float]:
        return (await self._embed([text], is_query=True))[0]

    async def get_embedding(self, text: str) -> List[float]:  # backward compatible alias
        return await self.embed_query(text)

    async def _embed(self, texts: List[str], is_query: bool) -> List[List[float]]:
        if not texts:
            return []
        p = self.resolved_provider()
        if p == "gemini":
            return await self._gemini_embed(texts, is_query)
        if p == "local":
            return await self._local_embed(texts, is_query)
        return [self._hash_embedding(t) for t in texts]

    # ------------------------------------------------------------------ gemini
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=60.0, transport=self._transport)

    @staticmethod
    def _gemini_error_text(resp: httpx.Response) -> str:
        try:
            msg = resp.json().get("error", {}).get("message", "")
        except Exception:
            msg = ""
        msg = msg or resp.text[:300]
        hint = {
            400: "Request hoặc API key không hợp lệ.",
            401: "API key không hợp lệ.",
            403: "API key không có quyền hoặc bị chặn.",
            404: "Model embedding không tồn tại hoặc đã ngừng hỗ trợ — hãy đổi model trong Cài đặt → Embedding.",
            429: "Hết quota/giới hạn tốc độ của Gemini API.",
        }.get(resp.status_code, "")
        return f"Gemini embedding lỗi {resp.status_code}. {hint} Chi tiết: {msg}".strip()

    async def _gemini_embed(self, texts: List[str], is_query: bool) -> List[List[float]]:
        key = self.gemini_key()
        if not key:
            raise EmbeddingError("Chưa có Gemini API Key (Cài đặt → Google Gemini).")
        model = self.gemini_model()
        url = f"{GEMINI_BASE}/models/{model}:batchEmbedContents"
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        task = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
        out: List[List[float]] = []

        async with self._client() as client:
            for i in range(0, len(texts), GEMINI_BATCH):
                batch = texts[i:i + GEMINI_BATCH]

                def build(with_task: bool):
                    reqs = []
                    for t in batch:
                        r: Dict[str, Any] = {
                            "model": f"models/{model}",
                            "content": {"parts": [{"text": (t or " ")[:GEMINI_MAX_CHARS]}]},
                            "outputDimensionality": GEMINI_DIM,
                        }
                        if with_task:
                            r["taskType"] = task
                        reqs.append(r)
                    return {"requests": reqs}

                with_task = True
                resp = None
                for attempt in range(5):
                    try:
                        resp = await client.post(url, headers=headers, json=build(with_task))
                    except httpx.HTTPError as e:
                        if attempt == 4:
                            raise EmbeddingError(f"Không kết nối được Gemini API: {e}")
                        await _sleep(min(2 ** attempt, 20))
                        continue
                    if resp.status_code == 200:
                        break
                    if resp.status_code == 400 and with_task and "task" in resp.text.lower():
                        with_task = False  # model without taskType support: retry once without it
                        continue
                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                        await _sleep(min(2 ** attempt * 2, 30))
                        continue
                    raise EmbeddingError(self._gemini_error_text(resp))

                if resp is None or resp.status_code != 200:
                    raise EmbeddingError("Gemini embedding không phản hồi hợp lệ.")
                data = resp.json()
                embs = data.get("embeddings", [])
                if len(embs) != len(batch):
                    raise EmbeddingError("Gemini trả về số vector không khớp số đoạn văn bản.")
                for e in embs:
                    values = e.get("values", [])
                    if not values:
                        raise EmbeddingError("Gemini trả về vector rỗng.")
                    out.append(_normalize(values))
        return out

    # ------------------------------------------------------------------- local
    def _load_local(self, model_id: str):
        """Load (and on first use download) a fastembed model. Blocking: run in a thread."""
        with self._local_lock:
            if model_id in self._local_models:
                return self._local_models[model_id]
            # Don't hammer a model that just failed to download (fastembed retries for ~1 min each time)
            failed = self._local_failures.get(model_id)
            if failed and time.monotonic() - failed[0] < LOCAL_RETRY_COOLDOWN:
                raise EmbeddingError(failed[1])
            try:
                from fastembed import TextEmbedding
            except Exception:
                raise EmbeddingError(
                    "Chưa cài fastembed. Chạy: pip install -r backend/requirements-local.txt")
            if model_id not in _LOCAL_BY_ID:
                raise EmbeddingError(f"Model local không được hỗ trợ: {model_id}")
            try:
                LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                model = TextEmbedding(model_name=model_id, cache_dir=str(LOCAL_CACHE_DIR))
            except Exception as e:
                msg = (f"Không tải/nạp được model local '{model_id}': {e}. "
                       f"Lần đầu cần Internet (~{_LOCAL_BY_ID[model_id]['size_gb']} GB).")
                self._local_failures[model_id] = (time.monotonic(), msg)
                raise EmbeddingError(msg)
            self._local_failures.pop(model_id, None)
            self._local_models[model_id] = model
            return model

    def _local_embed_sync(self, texts: List[str], is_query: bool) -> List[List[float]]:
        model_id = self.local_model()
        model = self._load_local(model_id)
        prefixed = _LOCAL_BY_ID[model_id]["prefixed"]
        prefix = ("query: " if is_query else "passage: ") if prefixed else ""
        try:
            vecs = list(model.embed([prefix + (t or " ") for t in texts], batch_size=16))
        except Exception as e:
            raise EmbeddingError(f"Model local lỗi khi tính embedding: {e}")
        return [_normalize(v) for v in vecs]

    async def _local_embed(self, texts: List[str], is_query: bool) -> List[List[float]]:
        return await asyncio.to_thread(self._local_embed_sync, texts, is_query)

    # -------------------------------------------------------------------- hash
    def _hash_embedding(self, text: str) -> List[float]:
        """Legacy hashed bag-of-words (+ character 3-grams). Lexical only, not semantic."""
        vec = np.zeros(HASH_DIM, dtype=np.float32)
        words = re.findall(r"\w+", (text or "").lower(), re.UNICODE)
        if not words:
            return vec.tolist()
        counts: Dict[str, int] = {}
        for w in words:
            counts[w] = counts.get(w, 0) + 1
        for word, count in counts.items():
            h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            sign = 1.0 if (h // HASH_DIM) % 2 == 0 else -1.0
            vec[h % HASH_DIM] += sign * (1.0 + math.log(count))
            if len(word) >= 3:
                for i in range(len(word) - 2):
                    hn = int(hashlib.sha256(word[i:i + 3].encode("utf-8")).hexdigest(), 16)
                    s2 = 1.0 if (hn // HASH_DIM) % 2 == 0 else -1.0
                    vec[hn % HASH_DIM] += s2 * 0.5
        return _normalize(vec)

    # ------------------------------------------------------------------- probe
    async def probe(self) -> Dict[str, Any]:
        """Embed one sentence with the active provider; used by the 'Kiểm tra' button."""
        t0 = time.perf_counter()
        try:
            vec = (await self._embed(["Xin chào, đây là câu kiểm tra embedding."], is_query=False))[0]
        except EmbeddingError as e:
            return {"ok": False, "provider": self.resolved_provider(), "tag": self.active_tag(),
                    "error": str(e)}
        return {"ok": True, "provider": self.resolved_provider(), "tag": self.active_tag(),
                "dim": len(vec), "ms": int((time.perf_counter() - t0) * 1000)}


embedding_service = EmbeddingService()
