"""RAG chatbot for Samsung phone questions.

Pipeline per question:
  1. Understand  – resolve phone names, detect aspects (camera, battery ...), ranking & comparison intent
  2. Retrieve    – structured retrieval from the DB (spec chunks for the phones/aspects, ranking tables)
                   + vector search over all spec chunks for anything else
  3. Generate    – open-source LLM answers strictly from the retrieved context
                   (deterministic template answer if no LLM is configured or the call fails)
Session memory keeps recent turns and the phones last discussed, so follow-ups like
"and its battery?" work.
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Phone
from app.db.repository import METRICS, list_phones, rank_phones
from app.llm import get_llm
from app.rag import aspects as A
from app.rag.documents import Chunk, build_chunks
from app.rag.entities import PhoneMatcher
from app.rag.retriever import SpecRetriever

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a knowledgeable, concise assistant for Samsung Galaxy smartphones.
Answer ONLY using the facts in the CONTEXT (scraped from GSMArena). Rules:
- Quote concrete numbers (MP, mAh, Hz, scores, prices) exactly as given in the context.
- For comparisons, compare the phones side by side and say which is better for each point and overall.
- For "best"/ranking questions, use the RANKING tables; mention the winner and runners-up.
- Benchmark scores from different AnTuTu versions (v8/v9/v10) are not directly comparable; prefer GeekBench when they differ.
- Prices are GSMArena's current listed prices, which may differ from launch prices.
- If the context does not contain the answer, say so briefly and mention which phones you have data for.
Use short paragraphs or bullet points. Do not invent specifications."""

DEFAULT_CATEGORIES = ("Display", "Platform", "Main Camera", "Battery", "Misc")
REVERSE_LOWER_BETTER = {"expensive", "priciest", "pricier", "heaviest", "heavier", "heavy"}


@dataclass
class QueryAnalysis:
    phones: list[Phone]
    aspects: list[A.Aspect]
    ranking_ascending: bool | None
    intent: str
    used_memory: bool = False


@dataclass
class ChatResult:
    answer: str
    session_id: str
    intent: str
    phones: list[str]
    aspects: list[str]
    sources: list[str]
    llm: str
    context: str = ""

    def as_dict(self, include_context: bool = False) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "context"}
        if include_context:
            d["context"] = self.context
        return d


@dataclass
class _Session:
    history: list[tuple[str, str]] = field(default_factory=list)
    last_phone_ids: list[int] = field(default_factory=list)


class ChatBot:
    def __init__(self, session_factory: sessionmaker, llm=None, use_llm: bool = True):
        self.session_factory = session_factory
        if llm is not None:
            self.llm, self.llm_name = llm, getattr(llm, "model_name", None) or type(llm).__name__
        elif use_llm:
            self.llm, info = get_llm()
            self.llm_name = f"{info.provider}:{info.model}" if info.model else info.provider
        else:
            self.llm, self.llm_name = None, "none"
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock = threading.Lock()
        self.refresh()

    # ------------------------------------------------------------------ index
    def refresh(self) -> None:
        """(Re)load phones from the DB and rebuild the vector index."""
        with self.session_factory() as db:
            phones = list_phones(db)
            db.expunge_all()
        self.phones = phones
        self.by_id = {p.id: p for p in phones}
        self.matcher = PhoneMatcher(phones)
        self.chunks = build_chunks(phones)
        self.retriever = SpecRetriever(self.chunks)
        log.info("Chatbot index built: %d phones, %d chunks (%s)", len(phones), len(self.chunks), self.retriever.backend)

    # ---------------------------------------------------------------- session
    def _session(self, session_id: str) -> _Session:
        with self._lock:
            sess = self._sessions.pop(session_id, None) or _Session()
            self._sessions[session_id] = sess
            while len(self._sessions) > 1000:
                self._sessions.popitem(last=False)
            return sess

    def reset_session(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    # ------------------------------------------------------------- understand
    def analyze(self, question: str, sess: _Session | None = None) -> QueryAnalysis:
        phones = self.matcher.find(question)
        aspects = A.detect_aspects(question)
        ranking = A.detect_ranking(question)
        catalog = A.is_catalog_question(question)
        used_memory = False
        if (not phones and not catalog and sess and sess.last_phone_ids and A.is_follow_up(question)
                and (ranking is None or A.is_comparison(question))):
            phones = [self.by_id[i] for i in sess.last_phone_ids if i in self.by_id]
            used_memory = bool(phones)

        if catalog and not phones:
            intent = "catalog"
        elif len(phones) >= 2:
            intent = "comparison"
        elif ranking is not None and not phones:
            intent = "ranking"
        elif len(phones) == 1:
            intent = "spec_lookup"
        else:
            intent = "general"
        return QueryAnalysis(phones, aspects, ranking, intent, used_memory)

    # --------------------------------------------------------------- retrieve
    def _ranking_tables(self, qa: QueryAnalysis, question: str) -> list[str]:
        aspects = [a for a in qa.aspects if a.metrics] or [A.ASPECTS["performance"]]
        words = set(question.lower().replace("?", " ").split())
        tables, seen = [], set()
        with self.session_factory() as db:
            for aspect in aspects[:2]:
                primary = A.ranking_metric(aspect, question)
                cols = [primary] + [m for m in aspect.metrics if m != primary]
                for col in cols[:3]:
                    if col in seen or col is None:
                        continue
                    seen.add(col)
                    metric = METRICS[col]
                    asc = None  # metric's natural "better first" order
                    if col == primary:
                        if metric.higher_is_better and qa.ranking_ascending:   # "smallest screen", "oldest"
                            asc = True
                        elif not metric.higher_is_better and words & REVERSE_LOWER_BETTER:  # "most expensive"
                            asc = False
                    rows = rank_phones(db, col, limit=len(self.phones), ascending=asc)
                    if not rows:
                        continue
                    order = "lowest first" if (asc if asc is not None else not metric.higher_is_better) else "highest first"
                    lines = [f"RANKING by {metric.label} ({order}; {len(rows)} of {len(self.phones)} phones have this data):"]
                    for i, p in enumerate(rows, 1):
                        extra = ""
                        if col == "antutu_score" and p.antutu_version:
                            extra = f" [{p.antutu_version}]"
                        lines.append(f"{i}. {p.name}: {metric.fmt(getattr(p, col))}{extra}")
                    tables.append("\n".join(lines))
        return tables

    def _comparison_table(self, phones: list[Phone], aspects: list[A.Aspect]) -> str:
        cols: list[str] = []
        for a in aspects or [A.ASPECTS[n] for n in ("display", "performance", "camera", "battery", "price")]:
            cols += [m for m in a.metrics if m not in cols]
        if not cols:
            return ""
        header = "| Metric | " + " | ".join(p.name for p in phones) + " |"
        lines = ["COMPARISON TABLE:", header, "|" + "---|" * (len(phones) + 1)]
        for col in cols:
            metric = METRICS[col]
            vals = [getattr(p, col) for p in phones]
            if all(v is None for v in vals):
                continue
            cells = [metric.fmt(v) + (f" [{p.antutu_version}]" if col == "antutu_score" and p.antutu_version else "")
                     for v, p in zip(vals, phones)]
            lines.append(f"| {metric.label} | " + " | ".join(cells) + " |")
        return "\n".join(lines)

    def retrieve(self, question: str, qa: QueryAnalysis) -> tuple[list[Chunk], list[str]]:
        chunks: list[Chunk] = []
        extras: list[str] = []
        categories = [c for a in qa.aspects for c in a.categories]

        def add(c: Chunk) -> None:
            if c not in chunks:
                chunks.append(c)

        if qa.phones:
            for p in qa.phones:
                for c in self.retriever.chunks_for(p.id, ["Overview"] + (categories or list(DEFAULT_CATEGORIES))):
                    add(c)
            k = 2 * len(qa.phones)
            for c, _ in self.retriever.search(question, k=k, phone_ids=[p.id for p in qa.phones], categories=categories):
                add(c)
            if qa.intent == "comparison":
                extras.append(self._comparison_table(qa.phones, qa.aspects))
        elif qa.intent == "ranking":
            extras.extend(self._ranking_tables(qa, question))
        elif qa.intent == "catalog":
            extras.append("PHONES IN DATABASE:\n" + "\n".join(
                f"- {p.name} ({p.release_year}), {p.display_size_in}\" display, {p.chipset.splitlines()[0] if p.chipset else ''}"
                for p in self.phones))
        else:
            for c, score in self.retriever.search(question, categories=categories):
                if score > 0.05:
                    add(c)
            if qa.aspects and any(a.metrics for a in qa.aspects):
                extras.extend(self._ranking_tables(qa, question)[:1])
        return chunks, [e for e in extras if e]

    # --------------------------------------------------------------- generate
    def _build_context(self, chunks: list[Chunk], extras: list[str]) -> str:
        parts = extras + [c.text for c in chunks]
        if not parts:
            parts = ["(no matching data)"]
        parts.append("Phones available in the database: " + ", ".join(p.name for p in self.phones))
        return "\n\n".join(parts)

    def ask(self, question: str, session_id: str | None = None) -> ChatResult:
        question = question.strip()
        session_id = session_id or uuid.uuid4().hex
        sess = self._session(session_id)
        qa = self.analyze(question, sess)
        chunks, extras = self.retrieve(question, qa)
        context = self._build_context(chunks, extras)

        answer, llm_used = None, "none"
        if self.llm is not None:
            messages = [SystemMessage(content=SYSTEM_PROMPT)]
            for q, a in sess.history[-settings.chat_history_turns:]:
                messages += [HumanMessage(content=q), AIMessage(content=a)]
            note = ""
            if qa.used_memory:
                note = f"(The user is referring to: {', '.join(p.name for p in qa.phones)})\n"
            messages.append(HumanMessage(content=f"CONTEXT:\n{context}\n\n{note}QUESTION: {question}"))
            try:
                answer = self.llm.invoke(messages).content.strip()
                llm_used = self.llm_name
            except Exception as exc:
                log.warning("LLM call failed (%s); using template answer", exc)
        if not answer:
            from app.rag.fallback import template_answer

            answer = template_answer(question, qa, chunks, extras, self.phones)

        with self._lock:
            sess.history.append((question, answer))
            del sess.history[:-20]
            if qa.phones:
                sess.last_phone_ids = [p.id for p in qa.phones]

        sources = [c.id for c in chunks] + [e.split("\n", 1)[0].rstrip(":") for e in extras]
        return ChatResult(answer, session_id, qa.intent, [p.name for p in qa.phones],
                          [a.name for a in qa.aspects], sources, llm_used, context)
