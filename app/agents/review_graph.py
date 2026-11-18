"""Multi-agent product-review pipeline built with LangGraph.

    ┌─────────────┐   ┌────────────────┐   ┌───────────────┐   ┌───────────────┐   ┌──────────────┐
    │ Coordinator │──▶│ Spec Retriever │──▶│ Market Analyst│──▶│ Review Writer │──▶│ Fact Checker │──▶ END
    └─────────────┘   └────────────────┘   └───────────────┘   └───────▲───────┘   └──────┬───────┘
     resolves phones    DB tools: specs,     ranks every metric        │ revise on        │
     & review focus     benchmarks, prices   vs. the catalogue;        └──unsupported─────┘
                                             strengths/weaknesses         numbers

* Spec Retriever – the "data agent": fetches specifications/benchmarks/prices from the database via tools.
* Market Analyst – turns raw numbers into insight: rank of each metric among all phones, strengths,
                   weaknesses, a data-driven score.
* Review Writer  – the "review agent": an open-source LLM writes the review from the spec sheet + analysis
                   (template writer when no LLM is configured).
* Fact Checker   – verifies every number+unit in the draft exists in the retrieved data and sends the draft
                   back to the writer with feedback if not (bounded by REVIEW_MAX_REVISIONS).
"""
from __future__ import annotations

import json
import logging
import operator
import re
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.agents.tools import find_phone, get_benchmarks, get_catalog_metrics, get_phone_specs, get_prices
from app.config import settings
from app.db.repository import METRICS
from app.llm import get_llm

log = logging.getLogger(__name__)

# metrics used for positioning, with the aspect they belong to
ANALYSIS_METRICS = {
    "display_size_in": "display", "ppi": "display", "peak_brightness_nits": "display",
    "geekbench_score": "performance", "ram_gb": "performance",
    "main_camera_mp": "camera", "optical_zoom_x": "camera", "selfie_camera_mp": "camera",
    "battery_mah": "battery", "battery_endurance_h": "battery", "charging_wired_w": "battery",
    "weight_g": "design", "price_usd": "value", "max_storage_gb": "storage",
}


class ReviewState(TypedDict, total=False):
    request: str
    focus: str | None
    phones: list[dict[str, Any]]
    spec_sheets: list[dict[str, Any]]
    analysis: list[dict[str, Any]]
    draft: str
    issues: list[str]
    revisions: int
    review: str
    error: str
    trace: Annotated[list[dict[str, Any]], operator.add]


def _log(agent: str, action: str, **detail) -> dict[str, Any]:
    return {"agent": agent, "action": action, **detail}


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def coordinator(state: ReviewState) -> ReviewState:
    """Resolve which phone(s) the user wants reviewed."""
    from app.rag.entities import PhoneMatcher
    from app.db.repository import list_phones
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        matches = PhoneMatcher(list_phones(db)).find(state["request"])
        phones = [{"id": p.id, "name": p.name} for p in matches]
    if not phones:  # fall back to the fuzzy single-phone lookup tool
        hit = find_phone.invoke({"name": state["request"]})
        phones = [{"id": hit["id"], "name": hit["name"]}] if hit else []
    if not phones:
        return {"error": f"No phone matching '{state['request']}' in the database.",
                "trace": [_log("Coordinator", "no phone found", request=state["request"])]}
    return {"phones": phones[:3], "revisions": 0,
            "trace": [_log("Coordinator", "resolved phones", phones=[p["name"] for p in phones[:3]],
                           focus=state.get("focus"))]}


def spec_retriever(state: ReviewState) -> ReviewState:
    """Data agent: pull specifications, benchmarks and prices from the database with tools."""
    sheets, calls = [], []
    for p in state["phones"]:
        sheet = get_phone_specs.invoke({"phone_id": p["id"]})
        sheet["benchmarks"] = get_benchmarks.invoke({"phone_id": p["id"]})
        sheet["prices"] = get_prices.invoke({"phone_id": p["id"]})
        sheet["id"] = p["id"]
        sheets.append(sheet)
        calls += [f"get_phone_specs({p['id']})", f"get_benchmarks({p['id']})", f"get_prices({p['id']})"]
    n_specs = sum(sum(len(v) for v in s["specs"].values()) for s in sheets)
    return {"spec_sheets": sheets,
            "trace": [_log("Spec Retriever", "fetched data", tool_calls=calls, spec_rows=n_specs)]}


def market_analyst(state: ReviewState) -> ReviewState:
    """Position each phone against the whole catalogue."""
    catalog = get_catalog_metrics.invoke({})
    analyses = []
    for sheet in state["spec_sheets"]:
        me = next(c for c in catalog if c["id"] == sheet["id"])
        rows, percentiles = [], {}
        for col, aspect in ANALYSIS_METRICS.items():
            value = me.get(col)
            values = [c[col] for c in catalog if c.get(col) is not None]
            if value is None or len(values) < 2:
                continue
            metric = METRICS[col]
            better = sum(1 for v in values if (v > value if metric.higher_is_better else v < value))
            rank = better + 1
            pct = 1 - better / (len(values) - 1) if len(values) > 1 else 1.0
            percentiles.setdefault(aspect, []).append(pct)
            rows.append({"metric": metric.label, "value": metric.fmt(value), "rank": rank, "of": len(values),
                         "aspect": aspect, "percentile": round(pct, 2)})
        strengths = [r for r in rows if r["percentile"] >= 0.75]
        weaknesses = [r for r in rows if r["percentile"] <= 0.25]
        aspect_scores = {a: round(5 + 5 * sum(v) / len(v), 1) for a, v in percentiles.items()}
        overall = round(sum(aspect_scores.values()) / len(aspect_scores), 1) if aspect_scores else None
        analyses.append({
            "phone": sheet["name"], "catalog_size": len(catalog), "positioning": rows,
            "strengths": [f"{r['metric']}: {r['value']} (#{r['rank']} of {r['of']})" for r in strengths],
            "weaknesses": [f"{r['metric']}: {r['value']} (#{r['rank']} of {r['of']})" for r in weaknesses],
            "aspect_scores": aspect_scores, "overall_score": overall,
        })
    return {"analysis": analyses,
            "trace": [_log("Market Analyst", "ranked metrics vs catalogue",
                           scores={a["phone"]: a["overall_score"] for a in analyses})]}


WRITER_PROMPT = """You are an expert smartphone reviewer writing for a tech website.
Write a detailed, well-structured product review in Markdown using ONLY the SPEC SHEET and MARKET ANALYSIS provided.
Structure:
# <Phone name> Review
**Verdict:** two-sentence summary with the overall score (use the analyst's overall_score, out of 10)
## Design & Build
## Display
## Performance
## Cameras
## Battery & Charging
## Software
## Price & Value
## Pros
## Cons
Rules: cite exact numbers from the data; explain what they mean for real users; use the analyst's rankings
("#2 of 15 for battery endurance") to give context; AnTuTu scores of different versions are not comparable;
prices are current GSMArena listings. If several phones are given, write one comparative review and finish
with a "Which should you buy?" section. Never invent specifications."""


def _compact_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    keep = ("Launch", "Body", "Display", "Platform", "Memory", "Main Camera", "Selfie camera",
            "Sound", "Battery", "Misc", "Our Tests", "Features")
    return {**{k: v for k, v in sheet.items() if k not in ("specs", "id")},
            "specs": {k: v for k, v in sheet["specs"].items() if k in keep}}


def _llm_from(config: RunnableConfig | None):
    """LLM injected via graph config (tests / custom models) or the configured default."""
    injected = ((config or {}).get("configurable") or {}).get("llm")
    if injected is not None:
        return injected, getattr(injected, "model_name", None) or type(injected).__name__
    llm, info = get_llm()
    return llm, f"{info.provider}:{info.model}"


def review_writer(state: ReviewState, config: RunnableConfig) -> ReviewState:
    llm, llm_name = _llm_from(config)
    revision = state.get("revisions", 0)
    if llm is None:
        draft = template_review(state["spec_sheets"], state["analysis"], state.get("focus"))
        return {"draft": draft, "trace": [_log("Review Writer", "wrote template review (no LLM configured)")]}

    payload = {"spec_sheet": [_compact_sheet(s) for s in state["spec_sheets"]], "market_analysis": state["analysis"]}
    user = f"SPEC SHEET + MARKET ANALYSIS (JSON):\n{json.dumps(payload, ensure_ascii=False, default=str)}"
    if state.get("focus"):
        user += f"\n\nThe reader is especially interested in: {state['focus']}"
    if state.get("issues") and state.get("draft"):
        user += ("\n\nYour previous draft contained numbers not supported by the data:\n- "
                 + "\n- ".join(state["issues"]) + "\nRewrite the review fixing these (remove or correct them).")
    try:
        draft = llm.invoke([SystemMessage(content=WRITER_PROMPT), HumanMessage(content=user)]).content.strip()
        action = "revised review" if revision else "wrote review"
        return {"draft": draft, "trace": [_log("Review Writer", action, llm=llm_name)]}
    except Exception as exc:
        log.warning("Review LLM failed: %s", exc)
        draft = template_review(state["spec_sheets"], state["analysis"], state.get("focus"))
        return {"draft": draft, "trace": [_log("Review Writer", "LLM failed, wrote template review", error=str(exc))]}


UNIT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(mAh|MP|Hz|W\b|g\b|GB|TB|nits|inches|in\b|\"|ppi|mm|fps|h\b|hours)", re.I)


def _numbers_in(obj: Any) -> set[float]:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text) if n.replace(",", "")}


def fact_checker(state: ReviewState, config: RunnableConfig) -> ReviewState:
    """Every number-with-unit in the draft must appear in the retrieved data."""
    known = _numbers_in(state["spec_sheets"]) | _numbers_in(state["analysis"])
    issues = []
    for m in UNIT_RE.finditer(state["draft"]):
        value = float(m.group(1).replace(",", ""))
        if value not in known:
            claim = m.group(0)
            if claim not in issues:
                issues.append(claim)
    revisions = state.get("revisions", 0)
    llm, _ = _llm_from(config)
    will_revise = bool(issues) and llm is not None and revisions < settings.review_max_revisions
    update: ReviewState = {
        "issues": issues,
        "trace": [_log("Fact Checker", "verified numeric claims", checked=len(UNIT_RE.findall(state["draft"])),
                       unsupported=issues, sent_back=will_revise)],
    }
    if will_revise:
        update["revisions"] = revisions + 1
    else:
        update["review"] = state["draft"]
    return update


def _route_after_check(state: ReviewState) -> str:
    return "finish" if state.get("review") else "revise"


def _route_after_coordinator(state: ReviewState) -> str:
    return "stop" if state.get("error") else "continue"


# ---------------------------------------------------------------------------
# Template writer (no-LLM mode)
# ---------------------------------------------------------------------------

def _spec(sheet: dict[str, Any], category: str, name: str) -> str | None:
    for row in sheet["specs"].get(category, []):
        n, _, v = row.partition(": ")
        if n.lower() == name.lower():
            return v.replace("\n", "; ")
    return None


def template_review(sheets: list[dict[str, Any]], analyses: list[dict[str, Any]], focus: str | None) -> str:
    parts = []
    for sheet, an in zip(sheets, analyses):
        km = sheet["key_metrics"]
        fmt = lambda col: METRICS[col].fmt(km.get(col))  # noqa: E731
        score = an["overall_score"]
        strengths = an["strengths"][:3] or ["a balanced spec sheet"]
        sc = an["aspect_scores"]
        parts.append(f"""# {sheet['name']} Review

**Verdict:** {score}/10 based on how its specs rank among the {an['catalog_size']} Samsung phones in our database.
Its standout points are {', '.join(strengths)}.

## Design & Build
{_spec(sheet, 'Body', 'Dimensions') or 'n/a'}, weighing {fmt('weight_g')}. Build: {_spec(sheet, 'Body', 'Build') or 'n/a'}.
Water/dust resistance: {sheet.get('ip_rating') or 'not specified'}. Colors: {_spec(sheet, 'Misc', 'Colors') or 'n/a'}.

## Display
{_spec(sheet, 'Display', 'Size') or 'n/a'} – {sheet.get('display_type') or ''}.
Resolution {_spec(sheet, 'Display', 'Resolution') or 'n/a'}. Display score: {sc.get('display', 'n/a')}/10.

## Performance
Powered by {(sheet.get('chipset') or 'n/a').replace(chr(10), ' / ')} with up to {fmt('ram_gb')} RAM.
GeekBench: {fmt('geekbench_score')}; AnTuTu: {fmt('antutu_score')} ({sheet.get('antutu_version') or 'n/a'}).
Performance score: {sc.get('performance', 'n/a')}/10.

## Cameras
Main: {_spec(sheet, 'Main Camera', 'Triple') or _spec(sheet, 'Main Camera', 'Quad') or _spec(sheet, 'Main Camera', 'Dual') or 'n/a'}.
Video: {_spec(sheet, 'Main Camera', 'Video') or 'n/a'}.
Selfie: {_spec(sheet, 'Selfie camera', 'Single') or 'n/a'}. Camera score: {sc.get('camera', 'n/a')}/10.

## Battery & Charging
{fmt('battery_mah')} battery; charging: {_spec(sheet, 'Battery', 'Charging') or 'n/a'}.
GSMArena endurance rating: {fmt('battery_endurance_h')}. Battery score: {sc.get('battery', 'n/a')}/10.

## Software
{sheet.get('os') or 'n/a'}.

## Price & Value
Currently listed at {_spec(sheet, 'Misc', 'Price') or 'n/a'}. Value score: {sc.get('value', 'n/a')}/10.

## Pros
""" + "\n".join(f"- {s}" for s in an["strengths"] or ["Well-rounded specifications"]) + """

## Cons
""" + "\n".join(f"- {w}" for w in an["weaknesses"] or ["No major weaknesses relative to the catalogue"]))
    if len(sheets) > 1:
        best = max(analyses, key=lambda a: a["overall_score"] or 0)
        parts.append(f"## Which should you buy?\nOn our data-driven score, **{best['phone']}** "
                     f"({best['overall_score']}/10) comes out ahead; see the strengths above to match your priorities.")
    if focus:
        parts.append(f"_Requested focus: {focus}._")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_review_graph():
    g = StateGraph(ReviewState)
    g.add_node("coordinator", coordinator)
    g.add_node("spec_retriever", spec_retriever)
    g.add_node("market_analyst", market_analyst)
    g.add_node("review_writer", review_writer)
    g.add_node("fact_checker", fact_checker)
    g.add_edge(START, "coordinator")
    g.add_conditional_edges("coordinator", _route_after_coordinator, {"continue": "spec_retriever", "stop": END})
    g.add_edge("spec_retriever", "market_analyst")
    g.add_edge("market_analyst", "review_writer")
    g.add_edge("review_writer", "fact_checker")
    g.add_conditional_edges("fact_checker", _route_after_check, {"revise": "review_writer", "finish": END})
    return g.compile()


_graph = None


def generate_review(request: str, focus: str | None = None, llm=None) -> dict[str, Any]:
    global _graph
    if _graph is None:
        _graph = build_review_graph()
    config = {"configurable": {"llm": llm}} if llm is not None else None
    state = _graph.invoke({"request": request, "focus": focus, "trace": []}, config=config)
    return {
        "request": request,
        "phones": [p["name"] for p in state.get("phones", [])],
        "review": state.get("review"),
        "analysis": state.get("analysis"),
        "unsupported_claims": state.get("issues", []),
        "revisions": state.get("revisions", 0),
        "agent_trace": state.get("trace", []),
        "error": state.get("error"),
    }
