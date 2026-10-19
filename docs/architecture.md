# Architecture

All models run on the VM: Qwen3-4B-Instruct-2507 (Ollama) for analysis, bge-m3 (Ollama) for comps embeddings, PaddleOCR PP-OCRv5 for scanned pages. Nothing leaves the machine except calls to official open-data APIs during the offline corpus and trend builds.

## System

```mermaid
flowchart LR
  subgraph Clients
    UI[Streamlit UI :8501]
    CLI[bsa CLI]
  end
  subgraph API[FastAPI :8100]
    J[POST /v1/jobs] --> Q[(in-process queue)]
    S[SSE /v1/jobs/id/events]
    R[GET /v1/reports/key]
  end
  UI --> J
  UI --> S
  UI --> R
  Q --> W[worker]
  W --> ING[ingest]
  CLI --> ING
  ING --> PIPE[LangGraph pipeline]
  PIPE --> DB[(SQLite jobs + report files)]
  ING -->|scanned Latin pages| DOCQNA[DOC_QnA PaddleOCR :5002]
  ING -->|Devanagari pages| PADDLE[local PaddleOCR CPU]
  PIPE --> OLL[Ollama :11434 qwen3:4b-instruct]
  PIPE -->|comps| QD[(Qdrant bsa_comps)]
  PIPE --> KB[[knowledge/ OKF bundle]]
  PIPE --> PR[[prompts/ versioned Jinja2]]
  subgraph Offline
    CB[bsa corpus build] -->|Wikipedia + Wikidata + IMDb| QD
    TR[bsa trends refresh] -->|Wikimedia pageviews| KB
  end
```

## Ingest

```mermaid
flowchart LR
  F[file or text] --> D{format}
  D -->|txt md fountain| T[rule parser]
  D -->|fdx| X[XML paragraph types]
  D -->|docx| W[paragraphs to rule parser]
  D -->|pdf png jpg| P{per page}
  P -->|text layer| DG[pdfplumber word boxes]
  P -->|scanned| O[OCR router]
  DG --> L[geometric layout classifier]
  O --> L
  T --> E[episodes, scenes, line IDs]
  X --> E
  W --> E
  L --> E
  E --> LG[language and code-mix]
  LG --> IR[ScriptIR]
  IR --> RD[deterministic render with token budget]
```

## Analysis graph

```mermaid
flowchart TD
  START((start)) --> SM[story_map]
  START --> CO[continuity]
  START --> RA[rating: prescan + classify + matrix + notices]
  SM -->|Send per episode| EP[episode_map xN]
  SM --> SU[summary]
  SM --> EM[emotion]
  SM --> MK[market: tropes + comps]
  SM --> AN[analytics, code only]
  EP --> EN[engagement x3, median]
  EP --> CL[cliffhanger]
  CL --> LO[localization per target]
  EN --> SG[suggestions]
  CL --> SG
  EN --> AL[alternatives: generate, blind judge x2, rescore]
  CL --> AL
  AN & CO & RA & SU & EM & MK & LO & SG & AL --> END((assemble))
```

## One LLM call

```mermaid
sequenceDiagram
  participant N as node
  participant C as RunContext.call
  participant O as Ollama
  participant V as validator
  N->>C: prompt id, schema, vars
  C->>O: [system preamble][rendered script][task + compact schema], format=schema, num_ctx=16384
  O-->>C: JSON (schema-constrained)
  C->>V: line IDs exist? quotes verbatim? node checks?
  alt errors
    C->>O: same messages + model answer + list of errors
    O-->>C: corrected JSON
    C->>V: re-check
    V-->>C: still bad: drop unsupported items, section = partial
  end
  C-->>N: parsed model + notes
```

The system preamble and the rendered script are identical for every node of a job, so Ollama reuses the cached prefix in its single slot (prefill drops from about 1.1 s to about 25 ms on repeated calls).
