"""Deterministic, data-grounded answers used when no LLM is available (or the LLM call fails).

They are built from the same retrieved context the LLM would see, so the system
stays fully functional offline – the LLM only adds natural-language polish.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.models import Phone
from app.db.repository import METRICS
from app.rag.documents import Chunk

if TYPE_CHECKING:  # pragma: no cover
    from app.rag.chatbot import QueryAnalysis


def _winner_lines(phones: list[Phone], cols: list[str]) -> list[str]:
    lines = []
    for col in cols:
        metric = METRICS[col]
        vals = [(p, getattr(p, col)) for p in phones if getattr(p, col) is not None]
        if len(vals) < 2:
            continue
        if col == "antutu_score" and len({p.antutu_version for p, _ in vals}) > 1:
            continue  # different AnTuTu versions are not comparable
        best = (max if metric.higher_is_better else min)(vals, key=lambda x: x[1])
        worst = (min if metric.higher_is_better else max)(vals, key=lambda x: x[1])
        if best[1] == worst[1]:
            lines.append(f"- **{metric.label}**: tie at {metric.fmt(best[1])}")
            continue
        pct = abs(best[1] - worst[1]) / worst[1] * 100 if worst[1] else 0
        lines.append(f"- **{metric.label}**: {best[0].name} leads with {metric.fmt(best[1])} vs "
                     f"{metric.fmt(worst[1])} ({pct:.0f}% {'more' if metric.higher_is_better else 'less'})")
    return lines


def template_answer(question: str, qa: "QueryAnalysis", chunks: list[Chunk], extras: list[str],
                    all_phones: list[Phone]) -> str:
    if qa.intent == "catalog":
        return extras[0].replace("PHONES IN DATABASE:", f"I have GSMArena data for {len(all_phones)} Samsung phones:")

    if qa.intent == "ranking" and extras:
        first = extras[0].split("\n")
        title, rows = first[0], first[1:]
        winner = rows[0].split(". ", 1)[1] if rows else "n/a"
        out = [f"**{winner.split(':')[0]}** comes out on top ({title.removeprefix('RANKING by ').split(' (')[0]}: "
               f"{winner.split(': ', 1)[1]}).", "", f"_{title}_"] + rows[:5]
        for extra in extras[1:]:
            lines = extra.split("\n")
            out += ["", f"_{lines[0]}_"] + lines[1:6]
        return "\n".join(out)

    if qa.intent == "comparison":
        cols: list[str] = []
        for a in qa.aspects or []:
            cols += [m for m in a.metrics if m not in cols]
        if not cols:
            cols = ["geekbench_score", "display_size_in", "main_camera_mp", "battery_mah", "battery_endurance_h", "price_usd"]
        names = " vs ".join(p.name for p in qa.phones)
        out = [f"**{names}**" + (f" – {', '.join(a.name for a in qa.aspects)}" if qa.aspects else ""), ""]
        out += _winner_lines(qa.phones, cols) or ["(no comparable numeric data)"]
        if extras:
            out += ["", extras[0].replace("COMPARISON TABLE:\n", "")]
        relevant = [c for c in chunks if c.category not in ("Overview",)]
        if relevant:
            out += ["", "Details:"] + [_chunk_md(c) for c in relevant[: 2 * len(qa.phones)]]
        return "\n".join(out)

    if qa.phones:
        if qa.aspects:
            wanted = {c.lower() for a in qa.aspects for c in a.categories}
            relevant = [c for c in chunks if c.category.lower() in wanted] or chunks
        else:
            relevant = chunks
        return "\n\n".join(_chunk_md(c) for c in relevant[:6])

    if chunks or extras:
        parts = [e for e in extras[:1]] + [_chunk_md(c) for c in chunks[:3]]
        return "Here is the most relevant information I found:\n\n" + "\n\n".join(parts)

    return ("I couldn't find that in my data. I can answer questions about: "
            + ", ".join(p.name for p in all_phones) + ".")


def _chunk_md(chunk: Chunk) -> str:
    title, _, body = chunk.text.partition("\n")
    return f"**{title}**\n{body}"
