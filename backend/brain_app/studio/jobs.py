"""Background 'write all sections' job so the browser can poll progress instead of holding one long request."""
import asyncio
import time
from typing import Any, Dict, Optional

from brain_app.studio import engine, quality, store


class WriteJobs:
    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}
        self.states: Dict[int, Dict[str, Any]] = {}

    def snapshot(self, doc_id: int) -> Dict[str, Any]:
        return dict(self.states.get(doc_id) or {"running": False, "done": 0, "total": 0, "current": None, "errors": []})

    def start(self, doc_id: int, only_missing: bool = True) -> bool:
        t = self._tasks.get(doc_id)
        if t and not t.done():
            return False
        self._tasks[doc_id] = asyncio.get_running_loop().create_task(self.run(doc_id, only_missing))
        return True

    async def wait(self, doc_id: int):
        t = self._tasks.get(doc_id)
        if t:
            await t

    async def run(self, doc_id: int, only_missing: bool):
        doc = store.get(doc_id)
        todo = [o for o in doc["outline"]
                if not (only_missing and doc["sections"].get(o["id"], {}).get("status") == "done")]
        st = {"running": True, "done": 0, "total": len(todo), "current": None, "errors": [], "started_at": time.time()}
        self.states[doc_id] = st
        store.mutate(doc_id, lambda d: d.__setitem__("status", "writing"))
        try:
            for o in todo:
                st["current"] = o["title"]
                try:
                    await engine.write_section(doc_id, o["id"])
                except engine.StudioError as e:
                    st["errors"].append({"section": o["title"], "error": str(e)})
                except Exception as e:  # keep going: one broken section must not lose the others
                    st["errors"].append({"section": o["title"], "error": f"Lỗi không mong đợi: {e}"})
                st["done"] += 1

            def finish(d):
                done_all = all(s.get("status") == "done" for s in d["sections"].values())
                d["status"] = "written" if done_all else "outline"
                if done_all and d["kind"] != "sop":
                    d["quality"] = quality.check_citations(d)
            store.mutate(doc_id, finish)
        finally:
            st.update(running=False, current=None, finished_at=time.time())


write_jobs = WriteJobs()
