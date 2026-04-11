# KD Platform Prototype

End-to-end Knowledge Domain platform demonstrating the CTO's vision: ADC chunking, semantic lifting, hybrid retrieval, CODEX evaluation, benchmarks, and reuse packaging. Runs locally with Docker Compose and a single PDF (ADP 3-0).

This is not production software. It is a reference implementation that shows how every component connects -- using real data, real embeddings, real LLM extraction, and real doctrinal evaluation.

## How This Maps to the CTO's Vision

| CTO Concept | Where It Lives | File(s) |
|-------------|---------------|---------|
| "Each KD maps to a dedicated table" (Steps 3-4) | kd_doctrine table with 5 column categories | `migrations/V001__create_kd_doctrine.sql` |
| "Atomic Doctrine Chunking" (Steps 3-4) | ADC integration producing 219 chunks with hierarchy + modality | `src/ingest.py` |
| "Semantic lifting models extract domain-relevant structure" (Steps 5-7) | Claude-based taxonomy extraction with confidence scores | `src/lift.py` |
| "Retrieval agent per KD" (Step 8) | Hybrid search with metadata filtering and confidence thresholds | `src/retrieve.py`, `api.py` |
| "CODEX conversation layer" (Steps 8-9) | Deterministic evaluation with causal chain traversal | `src/codex_retriever.py`, `src/compile_codex.py` |
| "Validate against real questions" (Step 9) | Benchmark runner with NDCG@10, MRR, precision/recall | `src/benchmark.py` |
| "Operationalize for reuse" (Step 10) | KD package export as portable artifact | `cli.py export` |

## How This Maps to Our Platform

| Prototype File | Production Target | What Changes |
|---------------|------------------|-------------|
| `migrations/V001` | Nexus Flyway migrations | Runs against Nexus PostgreSQL. Replaces `document_chunks`. |
| `src/ingest.py` | Prefect flow (`doctrine-ingest-v1`) | Registered alongside existing pipelines |
| `src/lift.py` | Prefect flow (`doctrine-lifting-v1`) | Same deployment pattern as ingestion |
| `src/retrieve.py` | Nexus FastAPI endpoint (`POST /nexus-service/kd/{kd_id}/retrieve`) | Added to existing nexus-service routes |
| `src/codex_retriever.py` | CODEX service CodexRetriever | Replaces MockCodexRetriever |
| `ui.py` | Demo only | Orcus UI or Victor would consume the retrieval endpoint |
| `cli.py export` | Reuse tooling (Bucket 1.5) | Becomes a Nexus admin command |

## Why This Order Matters

Each layer provides the substrate the next layer requires:

- **ADC** produces the facts (hierarchy, modality, glossary) that **lifting** enriches
- **Lifting** produces the taxonomy metadata that **retrieval** filters on
- **Retrieval** produces the ranked chunks that **CODEX** evaluates
- **Benchmarks** measure the quality of the whole stack

Skip any layer and the layers above it degrade measurably.

## Setup

### Prerequisites

- Docker Desktop
- Python 3.10+
- Anthropic API key

### Installation

```bash
git clone https://github.com/barrettdowns/Moat.git
cd Moat

# Start PostgreSQL with pgvector
docker compose up -d

# Install dependencies
pip install -e .

# Configure API key
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY
```

### Get the PDF

Place ADP 3-0 (publicly available from the Army Publishing Directorate) at `data/ADP_3-0.pdf`.

## Usage

### Step-by-step pipeline

```bash
# 1. Ingest: PDF -> ADC chunks -> embed -> store
python cli.py ingest --pdf data/ADP_3-0.pdf --config ../ADC/config/adp3_0.yaml

# 2. Lift: extract taxonomy fields via Claude
python cli.py lift --batch-size 20

# 3. Query: hybrid search with metadata filtering
python cli.py retrieve "What are the warfighting functions?" --top-k 5
python cli.py retrieve "What is required for unified action?" --filters '{"modality":"REQUIREMENT"}'

# 4. Compile CODEX objects from doctrine chunks
python cli.py compile-codex --max-sections 6

# 5. Run benchmarks
python cli.py benchmark

# 6. Export KD package
python cli.py export
```

### API server

```bash
uvicorn api:app --port 8000
```

Endpoints:
- `POST /kd/doctrine/retrieve` -- hybrid search with metadata filtering
- `POST /kd/doctrine/codex` -- CODEX doctrinal evaluation
- `GET /kd/doctrine/stats` -- chunk count, modality distribution, lift status
- `GET /health` -- service health

### Guided Tour UI

```bash
streamlit run ui.py
```

7-page interactive walkthrough: The Problem, ADC, Semantic Lifting, Retrieval (with before/after comparison), CODEX (with causal chain traces), Benchmarks, Package.

## Project Structure

```
kd-platform/
├── docker-compose.yml          # PostgreSQL + pgvector
├── pyproject.toml              # Dependencies
├── .env.example                # API key configuration
├── migrations/
│   └── V001__create_kd_doctrine.sql
├── config/
│   └── doctrine.yaml           # KD manifest
├── benchmarks/
│   └── doctrine_qa.json        # Q/A evaluation dataset
├── data/
│   └── compiled_codex_objects.json
├── src/
│   ├── ingest.py               # ADC -> embed -> store
│   ├── lift.py                 # Claude taxonomy extraction
│   ├── retrieve.py             # Hybrid search with filtering
│   ├── compile_codex.py        # ADC chunks -> CODEX objects
│   ├── codex_retriever.py      # CodexRetriever implementation
│   ├── benchmark.py            # IR metrics evaluation
│   ├── db.py                   # Database operations
│   └── embed.py                # Embedding abstraction
├── codex/                      # CODEX conversation layer (cloned)
├── api.py                      # FastAPI endpoints
├── ui.py                       # 7-page Streamlit guided tour
└── cli.py                      # CLI interface
```

## Benchmark Results

| Configuration | NDCG@10 | MRR | Precision@5 |
|---------------|---------|-----|-------------|
| Raw embeddings | 0.4848 | 0.5333 | 0.2000 |
| ADC (hybrid search) | 0.5130 | 0.5667 | 0.2267 |
| Full pipeline (with taxonomy filters) | 0.4771 | 0.5667 | 0.2000 |

ADC improves retrieval quality over raw embeddings (+5.8% NDCG@10). Taxonomy filtering trades breadth for precision when targeting specific doctrine types.

## Technical Notes

- **Embeddings:** all-MiniLM-L6-v2 (384 dims) for the prototype. Production uses text-embedding-3-large (1024 dims).
- **LLM:** Claude Sonnet for lifting and CODEX compilation. Evaluation path is deterministic (no LLM).
- **CODEX objects:** Pre-compiled from ADP 3-0 sections. Production uses a dedicated table with SME validation.
- **Benchmark Q/A:** 15 questions with paragraph-ID ground truth. Resolved to database records at runtime.
