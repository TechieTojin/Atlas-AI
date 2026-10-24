# Atlas

**Multi-agent research, grounded in your sources.**

Atlas is a local-first, full-stack AI research platform. Ask it a complex question and a team of LLM agents plans the investigation, gathers evidence from the web, your uploaded documents and its own research memory, critiques that evidence, loops until coverage is sufficient, and writes a report in which every claim carries a clickable citation back to its source. Alongside research, **Website Chat** lets you index a single webpage — or a set of pages you explicitly choose from one site — and ask questions answered only from that content, with each answer linked to the exact passage it came from.

Atlas exists to make AI research *checkable*. Language models are fluent but unaccountable; Atlas puts the evidence first: sources are collected and numbered before anything is written, citations are validated in code rather than trusted, and — with **Research Integrity** — each cited claim is checked against the passages it actually cites. The model runs **locally via Ollama**, so your documents and questions stay on your machine. The only external service is Tavily web search (free tier). Accurately put: *local LLM inference with Tavily web search*.

## Highlights

**Research**
- **Multi-agent workflow** (LangGraph): Planner → Researcher → Critic → (conditional research loop) → Synthesizer, with typed state, deterministic routing, iteration caps, plan validation with one bounded repair, and human-in-the-loop plan approval/editing.
- **FAST and DEEP modes**: FAST runs under an explicit, measured time budget for CPU-local models; DEEP keeps model thinking on for the structured stages and has no output caps.
- **Three source scopes**: *Web*, *Documents* (local RAG over uploaded PDF/TXT/MD), or *Web + Documents*, unified into one evidence model.
- **Full-page web research**: search discovery plus SSRF-safe page fetching, boilerplate stripping and query-relevant chunk selection.
- **Source quality**: a deterministic, explainable publisher assessment for every web source (category, tier, score, signals, warnings). It is explicitly *not* a truth score.
- **Report templates**: Standard, Academic, Technical, Executive, Literature Review, Comparison, and size-capped Custom; reports can be regenerated from existing evidence without re-researching.

**Evidence you can check**
- **Citation integrity enforced in code**: numbered sources, invalid citations stripped, model-written reference lists removed, one-shot citation repair, and a deterministic `## Sources` section.
- **Research Integrity**: persisted claims, per-claim citation verification, an evidence matrix, conservative contradiction detection and a transparent quality score — see [Research Integrity](#research-integrity).
- **Clickable citations and claim-level evidence inspector**: every inline `[n]` opens the source, its quality assessment, the evidence excerpts with provenance (origin, extraction mode, retrieval time, document page), and every claim that citation supports.
- **Follow-up questions (Ask Atlas)**: converse with a completed run; analytical follow-ups answer from existing evidence, research follow-ups gather new evidence while keeping existing citation numbers stable.

**Seeing how the research happened**
- **Research Map**: a map of what actually ran — question, plan, search rounds, evidence, critic and synthesis — reconstructed from persisted events, not a decorative workflow picture. Stages that did not occur are not drawn.
- **Timeline**: the same persisted events replayed in order, with play/pause and speed controls.
- **Research from here**: branch a new run from a node of the map. The parent run is never modified; the child records its lineage.

**Organising knowledge**
- **Projects**: group runs, documents, comparisons and memory into workspaces, with an overview, research, documents, comparisons and knowledge-graph tabs.
- **Persistent project findings**: cited findings are extracted deterministically from completed runs and fed to later research in the same project, so a project builds on what it already established.
- **Deterministic project Knowledge Graph**: derived from stored findings with no LLM call. Concepts and their co-occurrence are honestly labelled `RELATED_TO`, never presented as causal. A separate per-run graph has the model propose entities and relations, and Atlas validates each one against real sources.
- **Documents and Document Chat**: upload PDF/TXT/MD, then select documents and ask questions answered only from them, with citations back to the exact passage and page.
- **Collections**: save evidence, sources and notes into named collections; each saved item keeps a provenance link to where it came from, and the snapshot survives even if the original is deleted.
- **Run comparison**: compare 2 to 5 completed runs. Source overlap is computed exactly; the narrative is validated against the combined numbered sources.
- **History**: every run, with status, mode, template and date, linking back to the exact artifact.
- **Research memory**: exact and semantic reuse of past web evidence, with TTL, project scoping and preserved provenance.
- **Export**: Markdown and PDF (fpdf2, with HarfBuzz shaping for Devanagari and Malayalam).

## Research Integrity

A citation marker proves only that the report *pointed* somewhere. Research Integrity asks the next question: **does the cited passage actually support the claim?**

After a run completes, Atlas derives integrity artifacts from the report and evidence it already stored. The analysis is **deterministic and makes no model calls**, so opening the tab costs nothing and re-running it on the same report always produces the same verdicts. It can also be run on demand for runs completed before the feature existed.

### Claim model

Claims are not invented. Each one is a cited sentence lifted verbatim from the persisted report, stored with:

- the run (and project) it belongs to,
- the report section and its order in the document,
- the 1-based source numbers it cites,
- a normalised form used only to de-duplicate identical restatements.

Because a claim is the text you actually read, every verdict can be traced back to a specific sentence, its citations, the evidence passages behind them and the source those passages came from.

### Citation verification

Each claim is compared against the passages it cites and assigned one of:

| Status | Meaning |
|---|---|
| `SUPPORTED` | The cited passage contains the substance of the claim. |
| `PARTIALLY_SUPPORTED` | The passage is on topic and supports part of the claim, but not all of it. |
| `UNSUPPORTED` | The passage does not contain the substance of the claim. |
| `CONTRADICTED` | The passage appears to state the opposite, and figures disagree. |
| `NOT_VERIFIABLE` | No passage text is stored for the cited source, so the claim cannot be checked either way. |

`NOT_VERIFIABLE` is an honest "unknown", not a failure. **Citation presence is never treated as evidence of support.**

Verdicts come from transparent, evidence-derived signals that are shown to the user rather than hidden behind a number:

- **term overlap** — how much of the claim's distinctive vocabulary appears in the cited passage (light suffix folding, so *barriers* matches *barrier*),
- **numeric agreement** — whether figures stated by the claim appear in the passage,
- **evidence availability** — whether any passage text was stored at all,
- **polarity conflict** — whether the claim and passage state opposite directions on shared terms.

Confidence is reported as an interpretable band (**high / moderate / low**), not a fabricated probability. These are lexical and numeric heuristics, not semantic understanding: they are deliberately conservative and will not catch every subtle mismatch.

### Citation coverage vs citation support

These are different questions and Atlas keeps them apart:

- **Coverage** — do the report's claims carry citations at all?
- **Support** — do those cited passages actually back the claims?

A report can have 100 % coverage and still contain unsupported claims. When nothing could be verified, Atlas reports no support percentage at all rather than inventing one.

### Evidence matrix

The **Integrity** tab on a run lists every cited claim and lets you open it to inspect the full chain:

```
claim → verdict → confidence → signals → citations → evidence passages → source
```

Claims with recorded disagreements show them inline, with both passages quoted verbatim so you can judge the conflict yourself.

### Contradiction detection

Atlas records disagreements between the sources a single claim cites, classified as `DIRECT_CONTRADICTION`, `CONTEXTUAL_DISAGREEMENT`, `MIXED_EVIDENCE`, `OUTDATED_VS_CURRENT` or `DIFFERENT_SCOPE`.

The engine is deliberately conservative, because a fabricated disagreement is worse than a missed one. It does **not** treat the following as contradictions:

- different wording for the same fact,
- unrelated passages that merely share vocabulary,
- unitless or incidental numbers (a "5" in one passage against a "1.34" in another),
- same-unit figures describing different referents (silicon's 1.12 eV band gap against an optimal 1.34 eV),
- passages that demonstrably agree on a measured quantity — agreement blocks a flag even when negation wording is present.

Only figures carrying the **same unit** are compared, calendar years are treated as periods rather than quantities, and "outdated vs current" requires genuinely disjoint years. This reduces false positives; it does not make the detector infallible.

### Research quality score

A transparent, recomputable score — not an LLM rating. Components:

| Component | Weight | Source |
|---|---|---|
| Citation coverage | 0.20 | stored report evaluation |
| Citation support | 0.30 | verification verdicts (partial counts as a half) |
| Source diversity | 0.15 | distinct domains over cited sources |
| Source authority | 0.15 | stored publisher-class ratings, when the run recorded them |
| Evidence agreement | 0.10 | unresolved contradictions per claim |
| Evidence relevance | 0.10 | stored retrieval relevance |

Dimensions Atlas cannot compute for a given run are shown as **NOT AVAILABLE** and excluded; the remaining weights are renormalised, so a run is never silently punished for missing data and nothing is defaulted to zero. If no component can be computed, no overall score is shown. The formula is versioned with each stored score.

This measures how well a report is evidenced **by the material Atlas collected**. It is not a measure of whether the conclusions are true.

## Website Chat

Index a public webpage — or several pages you pick from one site — then chat with them. Every answer comes only from that indexed content and cites the exact passages it used.

**Single page**

```
URL
 → safe fetch (one page, bounded)
 → content extraction (structure-preserving, boilerplate removed)
 → section-aware chunking
 → embeddings (nomic-embed-text, the same model as document RAG)
 → retrieval (cosine + lexical signals, scoped to that page)
 → grounded answer from the local LLM
 → [n] citations that open the exact stored passage
```

**Multiple pages**

```
root URL
 → discover same-site pages (links and sitemap, robots.txt respected)
 → you choose which pages to index, up to a cap
 → Atlas indexes ONLY the pages you selected
 → cross-page retrieval over that selection
 → grounded answer citing the specific page each passage came from
```

Atlas **does not silently crawl a domain**. Discovery only proposes same-site pages; nothing is fetched for indexing until you select it, and the UI states this explicitly. Per-page outcomes are reported honestly: if a page fails, the other selected pages still index and the failure is shown with its reason ("3 of 4 pages indexed").

- **Grounded by construction.** Answers without citations, or containing figures that appear in none of the retrieved passages, are rejected. If the content does not contain the answer, Atlas says so instead of guessing.
- **Exact evidence.** A citation opens the stored passage in its original language, never a translation or a paraphrase. Citations are frozen snapshots, so they keep working after the site is re-indexed.
- **Responsive answering.** Your question appears immediately; a live card shows the real backend stage (searching, generating, checking citations) and the elapsed time, with a Cancel button. Answers have a hard deadline that includes any retry, and a cancelled or failed answer never leaves partial text behind.
- **Lifecycle.** Re-index with change detection (unchanged pages reuse their embeddings; changed content is swapped atomically into a new index version), duplicate-URL reuse, cancellation, delete with cascade, and recovery after a restart. No LLM call is made during ingestion.

**Security properties**
- `http`/`https` only; credentials in URLs rejected.
- SSRF protection: every resolved address must be public (loopback, private, link-local and cloud-metadata ranges are blocked, including IPv6-wrapped forms), and the connection is pinned to the validated address so DNS cannot change between check and connect.
- Redirects are followed manually and every hop is re-validated.
- Bounded fetches: connect/read/total timeouts, a decoded-size cap, a content-type allowlist. PDFs are directed to Documents.
- Webpage text is **untrusted evidence, never instructions**: it is fenced in delimiters the page cannot forge, prompt-injection attempts are reported as page content rather than obeyed, and answers cannot contain links or images.
- Pages behind logins, paywalls, CAPTCHAs or bot protection are not bypassed.

## Design

Atlas is a **warm, light-first research workspace**: an ivory canvas with white reading surfaces, charcoal text, a deep forest-emerald accent and restrained ochre, terracotta and plum for secondary meaning. Long-form reports get an editorial treatment — generous reading width, a serif display face for headings, and citation chips that stay legible inside prose. Decorative elements are kept subtle and never sit behind reading content.

- **No blue-dominant interface.** The palette is deliberately emerald and warm-neutral; native controls and focus rings use the brand accent rather than browser blue.
- **Dark theme** remains fully supported and shares the same semantic tokens.
- **Responsive** from 1440 px desktops down to 390 px phones, with no horizontal page scrolling on the main routes.
- **Accessible**: WCAG AA contrast, visible non-blue focus on every interactive control, labelled form fields, and dialogs exposed with proper modal semantics and Escape handling.

## Languages

The interface is fully translated into six languages: **English, Spanish, Hindi, German, French and Malayalam**. Generated output (reports, follow-ups, website answers) is a different matter: it depends on what the configured local model can produce reliably, so Atlas gates each language and feature on a recorded, validated capability instead of assuming every language works.

| Language | UI | Generated output with the default local models |
|---|---|---|
| English | ✔ | Full support (`qwen3:4b`); comparison narratives are validation-gated |
| Spanish | ✔ | Research reports, regeneration, follow-ups and Website Chat (`qwen3:4b`) |
| Hindi | ✔ | Limited: generated locally by `gemma4:e4b`, slower than English |
| German | ✔ | Limited: generated locally by `gemma4:e4b`, slower than English |
| French | ✔ | Not available with the current local models (UI only) |
| Malayalam | ✔ | Not available with the current local models (UI only) |

- Comparison narratives are validation-gated and are not offered in Spanish, Hindi or German.
- Project memory and the project Knowledge Graph work in English by design.
- When a requested language cannot be generated, Atlas says so up front and asks you to choose English explicitly; it never silently switches languages.
- Evidence always stays in its original language, and historical artifacts are **not** retranslated when you change the UI language.
- Language routing is configurable (`ATLAS_LANGUAGE_MODELS`), and which models you have pulled in Ollama determines which languages are available.

## Architecture

```mermaid
flowchart TD
    UI[React web UI] -->|REST + SSE| API[FastAPI]
    CLI[CLI] --> SVC
    API --> SVC[Services: research, integrity, follow-ups, comparisons,<br/>knowledge graphs, projects, documents, Website Chat]
    API --> LR[Language router + capability gating]
    SVC --> DB[(SQLite: runs, events, memory, documents, projects,<br/>findings, comparisons, graphs, websites, claims)]
    SVC --> G
    SVC --> WC

    subgraph G[LangGraph research workflow]
        P[Planner + validation/repair] --> R[Researcher]
        R --> C[Critic + invariants]
        C -->|insufficient| R
        C -->|sufficient / budget| S[Synthesizer + templates]
    end

    subgraph WC[Website Chat]
        F[SSRF-safe fetch: one page or selected pages] --> X[Extraction + chunking]
        X --> E[Embeddings + retrieval]
        E --> A[Grounded answer + citation checks]
    end

    R --> W[Tavily search]
    W --> FP[SSRF-safe full-page fetch<br/>+ extraction + chunk selection]
    R --> RAG[Document retrieval]
    R --> M[Research + project memory]
    S --> REP[Cited report → claims, follow-ups,<br/>comparisons, graphs, MD/PDF export]
    S --> INT[Research Integrity: claims, verification,<br/>contradictions, quality — deterministic, no LLM]
    G --> OL[Ollama: qwen3:4b / gemma4:e4b + nomic-embed-text]
    WC --> OL
```

### Source-quality methodology (and limits)

Deterministic rules over domain knowledge: curated publisher lists (academic, standards, research institutions, technical press, mainstream news, community platforms), TLD signals (.gov/.edu/.int, with caveats recorded as warnings), and URL signals (DOI boosts, blog/forum paths penalised, plain HTTP penalised). Unknown domains get a conservative neutral score plus an explicit warning rather than a judgment. **This measures publisher class, not claim truth.** The signals and warnings are stored so the UI can always show *why*.

## Tech Stack

**Backend:** Python 3.10 · LangGraph 1.x · LangChain 1.x · `langchain-ollama` · `langchain-tavily` · FastAPI + Uvicorn · SQLite (stdlib, versioned migrations, repository pattern) · Pydantic v2 · httpx · NumPy (vector similarity) · pypdf · fpdf2 + uharfbuzz (PDF export) · pytest

**Frontend:** React 18 · TypeScript · Vite · react-router · react-markdown · d3-force (graph layout) · Vitest + Testing Library

**Local models (via Ollama):** `qwen3:4b` (default generation model) · `gemma4:e4b` (Hindi and German) · `nomic-embed-text` (embeddings for documents, memory and Website Chat). Which models you pull determines which output languages Atlas offers; routing is configurable.

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+ and npm
- [Ollama](https://ollama.com/download)
- A free [Tavily](https://app.tavily.com) API key (web research only)

### 1. Models

```powershell
ollama pull qwen3:4b
ollama pull nomic-embed-text
ollama pull gemma4:e4b    # optional: Hindi and German output
```

Atlas only offers output languages whose routed model is available. Without `gemma4:e4b`, Hindi and German stay UI-only.

### 2. Backend

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env   # set TAVILY_API_KEY; everything else has working defaults
```

On macOS/Linux, use `source .venv/bin/activate` and `cp .env.example .env`.

### 3. Frontend

```powershell
cd frontend
npm install
```

### Running Atlas

```powershell
# API (repo root): http://127.0.0.1:8000, interactive docs at /docs
.venv\Scripts\python.exe -m src.api.server

# Web UI (second terminal): http://localhost:5173
cd frontend; npm run dev

# CLI
.venv\Scripts\python.exe -m src.main --query "..." --mode fast
```

If port 8000 is taken, set `ATLAS_API_PORT` for the API and point the UI at it with `VITE_API_TARGET` (for example `http://127.0.0.1:8010`). If port 5173 is already in use, Vite picks the next free port and prints it on startup.

## Configuration

All settings are optional except `TAVILY_API_KEY`; see `.env.example` for the full list. Notable settings:

| Variable | Default | Purpose |
|---|---|---|
| `ATLAS_MODEL` | `qwen3:4b` | Default generation model |
| `ATLAS_LANGUAGE_MODELS` | `hi=gemma4:e4b,de=gemma4:e4b` built in | Per-language model routing, e.g. `ml=qwen3:8b` |
| `ATLAS_EMBEDDING_MODEL` | `nomic-embed-text` | Embeddings for documents, memory and Website Chat |
| `ATLAS_DATA_DIR` | `data` | SQLite database and uploads |
| `ATLAS_PAGE_FETCH_PER_QUERY` | `2` (FAST: 1) | Full pages fetched per research query (0 disables) |
| `ATLAS_MEMORY_SEMANTIC_THRESHOLD` | `0.83` | Similarity needed for semantic evidence reuse |
| `ATLAS_PROJECT_MEMORY_THRESHOLD` | `0.65` | Similarity needed to reuse a project finding |
| `ATLAS_KG_MAX_NODES` / `ATLAS_KG_MAX_EDGES` | `40` / `60` | Knowledge-graph bounds |
| `ATLAS_WEBSITE_MAX_PAGES` | `20` | Pages selectable for multi-page Website Chat |
| `ATLAS_WEBSITE_MAX_BYTES` / `ATLAS_WEBSITE_MAX_CHUNKS` | `3000000` / `300` | Website Chat page size and index limits |
| `ATLAS_WEBSITE_CHAT_TIMEOUT_SECONDS` | `360` | Whole-answer deadline (can only be lowered) |
| `ATLAS_LLM_TIMEOUT_SECONDS` | `900` | Hard per-request LLM ceiling |
| `ATLAS_LLM_NUM_CTX` / `ATLAS_LLM_KEEP_ALIVE` | `8192` / `30m` | Ollama context size (shared by all stages) and keep-alive |
| `ATLAS_RETRIEVAL_WORKERS` | `4` | Concurrent search / page-fetch workers |
| `ATLAS_DEEP_RUN_BUDGET_SECONDS` | `0` (none) | Optional whole-run budget for DEEP |
| `ATLAS_PDF_FONT` | auto-detect | TTF for Unicode PDF export |
| `ATLAS_API_PORT` | `8000` | API port |

### FAST-mode performance budget

FAST runs the same graph under an explicit budget (`src/modes.py`), derived from measurements on a 4-core laptop CPU where qwen3:4b evaluates prompts at ~21–24 tok/s and generates at ~2.7–5 tok/s:

- **No hidden thinking** in any stage. With thinking on, Qwen spent ~11.5 min planning and ~19 min critiquing; the same calls without it took 77 s and 164 s.
- **Output caps and per-stage timeouts**: planner 450 tokens / 150 s, critic 320 / 150 s, synthesis 900 / 300 s, citation repair 180 s.
- **Bounded context**: at most 3 queries, 3 subquestions, 6 evidence items, 350 characters per evidence item for the critic, and a 4,200-character synthesis context.
- **Concurrent retrieval**: queries, and page fetches within a query, run in parallel. Results are merged in a fixed order, so the output stays deterministic.
- **9-minute run budget**: optional work (the critic pass, citation repair) is skipped rather than overrun. A critic timeout falls back to synthesis and is flagged. A synthesis timeout yields a labelled, fully cited evidence summary instead of discarding the research. Every fallback is recorded in metrics and shown in the UI.

DEEP keeps thinking on for structured stages and has no output caps. Website Chat sizes its context to the question: focused questions use a few strong passages and a short answer budget, broad questions up to six passages.

Per-call diagnostics come from Ollama's own statistics (calls, prompt and output tokens, context size, time per stage) and appear under **Metrics → Model usage**.

## API (summary)

Interactive OpenAPI docs are served at `/docs`.

```
Health/meta      GET /api/health · GET /api/templates · GET /api/capabilities/languages
Runs             POST/GET /api/runs · GET/DELETE /api/runs/{id} · POST .../cancel
                 GET .../events (SSE) · GET .../metrics · GET .../claims
                 POST .../plan/approve · POST .../plan/edit
                 POST .../regenerate · GET .../export?format=markdown|pdf
                 GET .../research-map · GET .../timeline · POST .../branches
Integrity        GET /api/runs/{id}/integrity · POST /api/runs/{id}/integrity/analyze
Follow-ups       POST/GET /api/runs/{id}/followups · GET /api/followups/{id}
                 POST /api/followups/{id}/cancel · GET /api/followups/{id}/events (SSE)
Comparisons      POST/GET /api/comparisons · GET/DELETE /api/comparisons/{id}
                 POST .../cancel · GET .../claims · GET .../export · GET .../events (SSE)
Knowledge graph  POST/GET /api/runs/{id}/knowledge-graph · GET .../events (SSE)
                 GET /api/projects/{id}/knowledge-graph
Projects         POST/GET /api/projects · GET/PATCH/DELETE /api/projects/{id}
                 GET /api/projects/{id}/overview
                 PUT/DELETE /api/projects/{id}/documents/{docId}
Documents        POST/GET /api/documents · GET/DELETE /api/documents/{id}
                 GET /api/documents/relationships
Document Chat    POST/GET /api/document-conversations · GET/DELETE /api/document-conversations/{id}
                 POST /api/document-conversations/{id}/messages
                 POST /api/document-messages/{id}/cancel
Collections      POST/GET /api/collections · GET/PATCH/DELETE /api/collections/{id}
                 POST /api/collections/{id}/items · PATCH/DELETE /api/collection-items/{id}
Website Chat     POST/GET /api/websites · GET/DELETE /api/websites/{id}
                 POST /api/websites/discover · GET /api/websites/{id}/pages
                 POST /api/websites/{id}/refresh · POST /api/websites/{id}/cancel
                 GET/POST /api/websites/{id}/conversations
                 GET/DELETE /api/website-conversations/{id}
                 POST /api/website-conversations/{id}/messages
                 POST /api/website-messages/{id}/cancel
```

## Database & migrations

One SQLite file (`data/atlas.db`, WAL) with versioned, non-destructive migrations (currently **v7**). Each migration only adds: v2 projects, follow-ups, comparisons and knowledge graphs; v3 project findings; v4 the output language of each run; v5 the Website Chat tables; v6 multi-page websites, grounded document chat and collections; v7 research integrity (claims, verifications, contradictions, quality scores). Older databases upgrade automatically on startup, existing runs stay readable, and no historical artifact is rewritten (covered by migration tests).

## Testing

```powershell
.venv\Scripts\python.exe -m pytest -q          # backend: fully offline
cd frontend
npm run typecheck; npm test -- --run; npm run build
```

Current state: **1050 backend tests and 325 frontend tests across 36 files pass**, the TypeScript typecheck is clean, and the production build succeeds. The backend suite runs fully offline (no network, Tavily or live Ollama) and covers each subsystem individually: workflow routing and plan validation, citation integrity, claim extraction and verification, contradiction precision, quality-score arithmetic and missing-data handling, SSRF and redirect attacks, extraction and chunking, memory and project findings, graph provenance, comparison validation, multilingual capability gating and Unicode handling, migrations, Website Chat ingestion, retrieval, grounding, deadlines, cancellation and prompt-injection resistance. The tests run locally; there is no CI pipeline yet.

Beyond the automated suites, the product has been exercised by hand in a real browser against live local models. That acceptance covered research and cancellation, reports, sources, evidence and integrity, projects and every project tab, the knowledge graph, research map and timeline, branching, documents and Document Chat, single-page and multi-page Website Chat, collections, comparisons, history, follow-ups and exports — at desktop, tablet and mobile widths, in light and dark themes, across all six UI languages, with accessibility checks (axe, keyboard and focus), SSRF/URL negative cases, refresh and restart persistence, and database-integrity verification before and after. This is local acceptance on one machine; it is not a claim that every runtime, model or environment has been validated.

## Security

Web pages, documents, website text and memory are **data, never instructions**: prompt-injection framing is applied everywhere, including page extraction, knowledge-graph prompts and Website Chat. SSRF protections cover both research page fetching and Website Chat. Custom templates cannot override citation or security rules. Evidence renders as text in the UI (no raw HTML paths) and as text in PDFs. Uploads keep sanitised names, size/type limits and checksums. API errors never expose tracebacks or secrets; Website Chat errors carry stable, translatable codes.

## Project Status & Limitations

Atlas is an active, local-first research project. Its current boundaries are deliberate:

- **CPU-local generation takes time.** Research runs take minutes on modest hardware, and Website Chat answers typically take one to three minutes on CPU. Every stage is bounded by measured budgets, and long work can be cancelled.
- **DEEP research is resource-intensive.** DEEP keeps model thinking on, runs the critic loop and has no output caps, so it needs appreciably more memory and time than FAST and benefits from a stronger machine. In the most recent local acceptance the environment was under heavy memory pressure, and while DEEP mode selection, planning, retrieval, evidence collection, critic engagement, live progress and cancellation (with a truthful cancelled state) were all verified, an end-to-end DEEP synthesis could not be completed in that constrained run. Set `ATLAS_DEEP_RUN_BUDGET_SECONDS` if you want DEEP bounded by a whole-run deadline.
- **Research Integrity is heuristic.** Verification uses lexical and numeric signals, not semantic understanding, and contradiction detection is tuned to avoid false positives rather than to catch everything. Treat verdicts as a reviewing aid, not a verdict on truth.
- **Critic integration with persisted integrity results is not implemented.** Verification and contradiction records are not yet fed back into the research critic.
- **Multilingual generation depends on the model.** Six UI languages are complete; generated output is offered only where the routed local model has been validated (see [Languages](#languages)).
- **Project memory and the project Knowledge Graph are English-only.** They are built from deterministic text analysis tuned for English.
- **Comparisons are validation-gated** and bounded by a time limit; on slow hardware a comparison can exceed it and is reported as timed out rather than returning a partial narrative. Overlap and source sections are always exact.
- **Website Chat indexes the pages you choose**, never a whole domain. Pages that need JavaScript to render, or sit behind logins, paywalls or CAPTCHAs, are reported as not indexable rather than bypassed.
- **Source quality is a publisher-class heuristic**, not a truth judgment. Excellent niche publishers score neutral.
- **Full-page extraction is HTML text only**: no JavaScript rendering and no OCR for scanned PDFs.
- **Single-process, single-user deployment** (worker threads, in-process event bus).

## Roadmap

**Planned Atlas Advanced capabilities — not implemented yet.** These are design targets, not current features:

- Global search across artifacts with a command palette
- Research notebook with pinned, provenance-linked items
- Reusable source library and research-ready source collections
- Branching from claims, evidence, sources and contradictions
- Explicit report versioning with semantic version diffs
- Watched topics with scheduled monitoring and change detection
- Structured data extraction into provenance-backed datasets, with CSV export and charts
- Research missions: objective → questions → bounded research → synthesis → recommendation
- A mission map over persisted mission execution
- Reusable research templates and a report/export studio
- A research dashboard and a persistent task queue
- A local model manager
- Collaboration (roles, comments) and secure read-only sharing
- A formal, versioned public API

**Other planned work:** feeding integrity results into the critic · OCR for scanned PDFs · cross-encoder reranking for memory/RAG · LangGraph checkpointing for mid-run restarts · multi-user deployment (Postgres + job queue) · tracing (LangSmith/OpenTelemetry) · continuous integration · Docker.

## License

Atlas is released under the [MIT License](LICENSE). It depends on third-party open-source packages (LangGraph, LangChain, FastAPI, React, fpdf2 and others) under their own licenses. The bundled fonts are distributed under the SIL Open Font License 1.1; see [`frontend/public/fonts/`](frontend/public/fonts) and [`src/export/fonts/`](src/export/fonts).
