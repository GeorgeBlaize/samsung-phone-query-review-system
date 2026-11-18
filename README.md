# Samsung Phone Query & Review System

An intelligent system that answers questions about Samsung Galaxy smartphones and writes detailed product reviews. It has four parts:

1. **Web scraping**: GSMArena spec pages are scraped with BeautifulSoup and stored in **PostgreSQL**.
2. **RAG chatbot**: an open-source LLM (Llama 3.1 through Ollama or the Hugging Face router) answers from data retrieved out of the database.
3. **Multi-agent system**: a **LangGraph** pipeline of five agents (retrieve specs → analyse → write review → fact-check).
4. **REST API**: a **FastAPI** service exposing chat, batch chat, reviews, rankings and comparisons.

```
GSMArena ──scraper──▶ PostgreSQL ──┬──▶ RAG retriever ──▶ LLM chatbot ──┐
 (BeautifulSoup)     phones          │   (spec chunks +                   ├──▶ FastAPI  /chat  /review ...
                     specifications  │    ranking tables)                 │
                     prices          └──▶ LangGraph agents ───────────────┘
                     benchmarks           Coordinator → Spec Retriever → Market Analyst
                                          → Review Writer ⇄ Fact Checker
```

---

## 1. Data scraping & storage

| | |
|---|---|
| Source | [GSMArena](https://www.gsmarena.com) spec pages for 15 phones: Galaxy S21/S21+/S21 Ultra, S22/S22+/S22 Ultra, S23/S23+/S23 Ultra/S23 FE, S24/S24+/S24 Ultra, Z Fold5, Z Flip5 ([app/scraper/targets.py](app/scraper/targets.py)) |
| Tooling | `requests` + `BeautifulSoup` (lxml). Requests are throttled (3 s), back off on HTTP 429 and honour `Retry-After`. Raw HTML is cached in `data/raw/`. |
| Parsing | [app/scraper/parser.py](app/scraper/parser.py) keeps **every** spec row (about 50 per phone) and derives normalised numeric columns: display size, refresh rate, PPI, peak brightness, chipset, RAM, storage, camera MP, optical zoom, battery mAh, wired and wireless charging W, weight, IP rating, AnTuTu and GeekBench scores (with version), GSMArena battery-test hours, and prices in USD/EUR/GBP/INR. |
| Export | `data/phones.json` holds the structured export. It is committed, so the database can be rebuilt without re-scraping. |

**Database schema** ([app/db/models.py](app/db/models.py), DDL in [db/schema.sql](db/schema.sql)):

| table | contents |
|---|---|
| `phones` | one row per phone with query-friendly normalised columns (used for rankings and comparisons) |
| `specifications` | every raw spec row: `category`, `name`, `value`, `position` |
| `prices` | listed price per currency |
| `benchmarks` | GSMArena lab tests: AnTuTu (per version), GeekBench, GFXBench, battery endurance and active-use scores, measured brightness, loudspeaker loudness |

## 2. RAG chatbot ([app/rag/](app/rag/))

Each question goes through three steps:

1. **Understand.** [entities.py](app/rag/entities.py) resolves phone names using longest-alias matching, so `"s23 ultra"` doesn't resolve to the S23, `"S22 plus"` resolves to the S22+, and `"fold 5"` resolves to the Z Fold5. [aspects.py](app/rag/aspects.py) detects the aspect (camera, battery, display, performance, price …) and the intent: *spec lookup*, *comparison*, *ranking* ("best", "cheapest"), *catalogue* or *general*.
2. **Retrieve.**
   - Spec chunks (one chunk per phone × category) for the phones and aspects mentioned.
   - Vector search over all chunks. TF-IDF is the default; `sentence-transformers` embeddings are optional.
   - SQL-built ranking tables for "best X" questions and comparison tables for "A vs B".
3. **Generate.** An open-source LLM answers strictly from that context. If no LLM is configured, or the call fails, a deterministic template answer is built from the same data, so the system always works.

Session memory supports follow-up questions: *"Compare the S23 and S22 performance"* followed by *"and what about their price?"*

Sample questions it handles:
- *What are the camera specs of the Samsung Galaxy S23?* (spec lookup)
- *Which Samsung phone has the best battery life?* (ranking by GSMArena endurance test, active-use score and capacity)
- *How does the Galaxy S23 compare to the S22 in terms of performance?* (comparison table plus who wins by how much)
- *What is the screen size of the Galaxy S22?* · *Which is the cheapest?* · *Which phones do you have?*

### LLM providers ([app/llm.py](app/llm.py))
All providers use LangChain's OpenAI-compatible client:

| `LLM_PROVIDER` | model | setup |
|---|---|---|
| `ollama` | `llama3.1:8b`, or `llama3.2:3b` on 8 GB RAM laptops (any Ollama model) | install [Ollama](https://ollama.com), then `ollama pull llama3.2:3b` and set `OLLAMA_MODEL=llama3.2:3b` |
| `huggingface` | `meta-llama/Llama-3.1-8B-Instruct` (any router model) | set `HF_TOKEN` |
| `openai` | `gpt-4o-mini` | set `OPENAI_API_KEY` (optional) |
| `none` | – | template answers only |
| `auto` (default) | – | uses HF if `HF_TOKEN` is set, otherwise a running Ollama, otherwise OpenAI, otherwise none |

## 3. Multi-agent review system ([app/agents/review_graph.py](app/agents/review_graph.py))

The pipeline is built with **LangGraph**:

| agent | role |
|---|---|
| **Coordinator** | resolves which phone or phones to review (one phone, or "S23 vs S22" for a comparative review) |
| **Spec Retriever** | data agent: calls DB tools ([tools.py](app/agents/tools.py)) `get_phone_specs`, `get_benchmarks` and `get_prices` |
| **Market Analyst** | ranks every key metric against the whole catalogue (e.g. *"GeekBench #1 of 15"*), finds strengths and weaknesses, computes aspect scores and an overall score out of 10 |
| **Review Writer** | review agent: the LLM writes a structured review covering verdict, design, display, performance, cameras, battery, software, value, and pros/cons |
| **Fact Checker** | extracts every number with a unit (mAh, MP, Hz, W, g, nits …) from the draft and checks it against the retrieved data. Unsupported claims send the draft **back to the writer** with feedback, bounded by `REVIEW_MAX_REVISIONS`. |

Each response includes the full `agent_trace`, showing which agent did what, which tools were called, and which claims were flagged.

## 4. API ([app/api/main.py](app/api/main.py))

Interactive docs are at **http://localhost:8000/docs**.

| method | endpoint | description |
|---|---|---|
| POST | `/chat` | `{"question": "...", "session_id": "optional"}` returns the answer, intent, phones, sources and LLM used |
| POST | `/chat/batch` | `{"questions": [...]}`: several queries in one shared session |
| DELETE | `/chat/{session_id}` | clear conversation memory |
| POST | `/review` | `{"phone": "Galaxy S23 Ultra", "focus": "camera"}` returns a multi-agent review with analysis and trace |
| GET | `/phones`, `/phones/{id\|slug\|name}` | catalogue / full spec sheet |
| GET | `/rankings/{metric}?limit=5` | e.g. `battery_mah`, `geekbench_score`, `price_usd` |
| GET | `/compare?phones=s23&phones=s22` | side-by-side metrics with the winner per metric |
| POST / GET | `/scrape` | re-scrape in the background and rebuild the index / check status |
| GET | `/health` | DB, LLM and retriever status |

```bash
curl -X POST localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"question": "How does the Galaxy S23 compare to the S22 in terms of performance?"}'
curl -X POST localhost:8000/review -H "Content-Type: application/json" -d '{"phone": "Galaxy S23"}'
```

---

## Running it

### Option A: Docker (PostgreSQL + API)
```bash
docker compose up --build                     # Postgres + API, loads data/phones.json
# with a local open-source LLM:
docker compose --profile llm up --build
docker compose exec ollama ollama pull llama3.1:8b
```

### Option B: local Python
```bash
python -m venv .venv && .venv\Scripts\activate          # Windows (source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
copy .env.example .env                                  # set DATABASE_URL, LLM settings

python -m app.scraper.run                    # scrape GSMArena into PostgreSQL (+ refresh data/phones.json)
# or, without network access:
python -m app.scraper.run --from-json data/phones.json

uvicorn app.api.main:app --reload            # API on http://localhost:8000/docs
python -m app.cli chat                       # terminal chatbot
python -m app.cli review "Galaxy S23" --trace
```
For a quick start without PostgreSQL, set `DATABASE_URL=sqlite:///./data/samsung_phones.db`.

### Tests
```bash
pytest -q
```
The tests cover the parser, phone-name resolution, the three sample queries, follow-up memory, the agent pipeline (including a fact-checker revision loop with a fake LLM), and every API endpoint.

## Project layout
```
app/
  config.py            settings from .env
  llm.py               open-source LLM factory (Ollama / Hugging Face / OpenAI / none)
  cli.py               terminal chat + review
  scraper/             targets, polite fetcher with cache, BeautifulSoup parser, CLI runner
  db/                  SQLAlchemy models, session, repository (upsert, lookups, rankings)
  rag/                 entity resolution, query aspects, chunking, retriever, chatbot, template fallback
  agents/              DB tools + LangGraph multi-agent review pipeline
  api/                 FastAPI app
data/phones.json       structured scrape export
db/schema.sql          PostgreSQL DDL
tests/                 pytest suite
```

## Notes
- **Pricing**: GSMArena lists *current* market prices, not launch prices, and the chatbot says so.
- **Benchmarks**: GSMArena tested older phones on GeekBench 5 and newer ones on GeekBench 6, which use different scales. They are stored as separate columns (`geekbench_score`, `geekbench6_score`), so rankings and comparisons only ever compare the same version. AnTuTu scores carry their version (v8/v9/v10) for the same reason.
- **Battery tests**: GSMArena replaced its old *endurance rating* with an *active use score* in 2024. The S24 series only has the new test and the S21/S22 series only the old one, so battery rankings show both tests plus raw capacity (mAh).
- **Rate limits**: GSMArena's search page sits behind a Cloudflare challenge, and the site rate-limits aggressively, sometimes with a `Retry-After` of several hours. The scraper therefore targets spec pages directly, caches them, and stops cleanly when it is rate-limited. Re-running it resumes from the cache.
