"""FastAPI service for the Samsung Phone Query & Review System.

Run:  uvicorn app.api.main:app --reload     ->  interactive docs at http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from app.db.models import Phone
from app.db.repository import METRICS, get_phone, list_phones, phone_record, phone_summary, rank_phones
from app.db.session import SessionLocal, init_db
from app.rag.chatbot import ChatBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

_bot: ChatBot | None = None
_bot_lock = threading.Lock()


def get_bot() -> ChatBot:
    global _bot
    with _bot_lock:
        if _bot is None:
            _bot = ChatBot(SessionLocal)
        return _bot


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    await run_in_threadpool(get_bot)
    yield


app = FastAPI(
    title="Samsung Phone Query & Review API",
    description="Ask questions about Samsung Galaxy phones (RAG chatbot over GSMArena data) "
                "and generate multi-agent product reviews.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=1000, examples=["What are the camera specs of the Samsung Galaxy S23?"])
    session_id: str | None = Field(None, description="Reuse to keep conversation context (follow-up questions)")
    include_context: bool = Field(False, description="Return the retrieved RAG context for debugging")


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    intent: str
    phones: list[str]
    aspects: list[str]
    sources: list[str]
    llm: str
    context: str | None = None


class BatchChatRequest(BaseModel):
    questions: list[str] = Field(..., min_length=1, max_length=20)
    session_id: str | None = None


class ReviewRequest(BaseModel):
    phone: str = Field(..., examples=["Galaxy S23 Ultra"], description="One phone, or several to compare ('S23 vs S22')")
    focus: str | None = Field(None, examples=["camera and battery"], description="Optional aspect to emphasise")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", tags=["meta"])
def root() -> dict[str, Any]:
    return {"service": app.title, "docs": "/docs",
            "endpoints": ["/health", "/phones", "/phones/{key}", "/rankings/{metric}", "/compare",
                          "/chat", "/chat/batch", "/review", "/scrape"]}


@app.get("/health", tags=["meta"])
def health() -> dict[str, Any]:
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
        count = db.scalar(select(func.count()).select_from(Phone))
    bot = get_bot()
    return {"status": "ok", "phones": count, "llm": bot.llm_name, "retriever": bot.retriever.backend,
            "chunks": len(bot.chunks)}


@app.get("/phones", tags=["phones"])
def phones() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        return [phone_summary(p) for p in list_phones(db)]


@app.get("/phones/{key}", tags=["phones"])
def phone_detail(key: str) -> dict[str, Any]:
    """Full spec sheet by id, slug or name (e.g. `s23-ultra`, `Galaxy S22`)."""
    with SessionLocal() as db:
        phone = get_phone(db, key.replace("-", " ") if not key.isdigit() and "_" not in key else key)
        if phone is None:
            raise HTTPException(404, f"Phone '{key}' not found")
        return phone_record(phone)


@app.get("/rankings/{metric}", tags=["phones"])
def rankings(metric: str, limit: int = Query(5, ge=1, le=50), ascending: bool | None = None) -> dict[str, Any]:
    if metric not in METRICS:
        raise HTTPException(400, f"Unknown metric. Choose one of: {', '.join(METRICS)}")
    m = METRICS[metric]
    with SessionLocal() as db:
        rows = rank_phones(db, metric, limit, ascending)
        return {"metric": metric, "label": m.label,
                "results": [{"rank": i, "name": p.name, "value": getattr(p, metric), "display": m.fmt(getattr(p, metric))}
                            for i, p in enumerate(rows, 1)]}


@app.get("/compare", tags=["phones"])
def compare(phones: list[str] = Query(..., min_length=2, examples=["s23", "s22"])) -> dict[str, Any]:
    with SessionLocal() as db:
        found = []
        for key in phones:
            p = get_phone(db, key)
            if p is None:
                raise HTTPException(404, f"Phone '{key}' not found")
            found.append(p)
        table = {}
        for col, m in METRICS.items():
            values = [getattr(p, col) for p in found]
            if all(v is None for v in values):
                continue
            present = [v for v in values if v is not None]
            best = (max if m.higher_is_better else min)(present)
            table[col] = {"label": m.label,
                          "values": {p.name: m.fmt(v) for p, v in zip(found, values)},
                          "best": [p.name for p, v in zip(found, values) if v == best] if len(present) > 1 else []}
        return {"phones": [p.name for p in found], "metrics": table}


@app.post("/chat", response_model=ChatResponse, tags=["chatbot"])
async def chat(req: ChatRequest) -> dict[str, Any]:
    result = await run_in_threadpool(get_bot().ask, req.question, req.session_id)
    return result.as_dict(include_context=req.include_context)


@app.post("/chat/batch", tags=["chatbot"])
async def chat_batch(req: BatchChatRequest) -> list[dict[str, Any]]:
    """Answer several questions in order (sharing one session, so later questions can refer to earlier ones)."""
    bot = get_bot()
    session_id = req.session_id
    out = []
    for q in req.questions:
        r = await run_in_threadpool(bot.ask, q, session_id)
        session_id = r.session_id
        out.append(r.as_dict())
    return out


@app.delete("/chat/{session_id}", tags=["chatbot"])
def reset_chat(session_id: str) -> dict[str, Any]:
    return {"session_id": session_id, "cleared": get_bot().reset_session(session_id)}


@app.post("/review", tags=["agents"])
async def review(req: ReviewRequest) -> dict[str, Any]:
    """Multi-agent review: Coordinator -> Spec Retriever -> Market Analyst -> Review Writer -> Fact Checker."""
    from app.agents.review_graph import generate_review

    result = await run_in_threadpool(generate_review, req.phone, req.focus)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


_scrape_state: dict[str, Any] = {"running": False, "last_result": None}


def _scrape_job() -> None:
    from app.scraper.run import scrape_all

    try:
        _scrape_state["last_result"] = scrape_all()
        get_bot().refresh()
    finally:
        _scrape_state["running"] = False


@app.post("/scrape", status_code=202, tags=["admin"])
def scrape(background: BackgroundTasks) -> dict[str, Any]:
    """Re-scrape GSMArena in the background and rebuild the RAG index."""
    if _scrape_state["running"]:
        return {"status": "already running"}
    _scrape_state["running"] = True
    background.add_task(_scrape_job)
    return {"status": "started"}


@app.get("/scrape", tags=["admin"])
def scrape_status() -> dict[str, Any]:
    return _scrape_state
