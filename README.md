# KD Platform -- Guided Tour

End-to-end Knowledge Domain platform prototype demonstrating the KD architecture: domain-specific chunking (ADC), semantic lifting with confidence scores, hybrid retrieval with metadata filtering, deterministic doctrinal evaluation (CODEX), benchmark infrastructure, and reusable KD packaging.

Built against 5 Army doctrine documents (ADP 3-0, FM 2-0, FM 3-12, FM 3-61, FM 5-0). 2,910 chunks, fully lifted, with modality classification, warfighting function extraction, echelon tagging, and confidence scores.

This is an interactive demo -- all data is pre-computed from a live prototype running against a real PostgreSQL/pgvector backend with real embeddings and real LLM extraction. No database or API keys required to run.

## Run Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## How This Maps to the Knowledge Domains Vision

| Concept | What the Demo Shows |
|---------|-------------------|
| Each KD maps to a dedicated table | `kd_doctrine` with 30+ columns across 5 categories (standard metadata, ADC chunk metadata, vector data, semantic lifting with confidence, JSONB overflow) |
| Atomic Doctrine Chunking (ADC) | 2,910 deterministic chunks with hierarchy paths, normative modality, glossary linkage -- zero LLM calls |
| Semantic lifting extracts domain-relevant structure | Warfighting function, echelon, doctrinal phase -- each with confidence scores from Claude-based extraction |
| Retrieval agent per KD | Hybrid search (vector + lexical) with metadata filtering, three-mode comparison |
| CODEX conversation layer | Deterministic evaluation with causal chain traversal -- SUPPORTED / CONDITIONAL / ABSTAIN |
| Validate against real questions | Benchmark runner measuring NDCG@10, MRR, Precision@5 across retrieval modes |
| Operationalize for reuse | KD package export: schema migration, config, benchmark Q/A set, manifest |

## Why This Order Matters

Each layer provides the substrate the next layer requires:

- **ADC** produces the facts (hierarchy, modality, glossary) that **lifting** enriches
- **Lifting** produces the taxonomy metadata that **retrieval** filters on
- **Retrieval** produces the ranked chunks that **CODEX** evaluates
- **Benchmarks** measure the quality of the whole stack

Skip any layer and the layers above it degrade measurably.

## Tabs

| Tab | What It Shows |
|-----|---------------|
| 1. The Problem | Side-by-side: commodity 5-column schema vs. 30+ column KD schema |
| 2. ADC | Deterministic chunking with hierarchy, modality, glossary linkage -- zero LLM calls |
| 3. Semantic Lifting | LLM-extracted domain fields (warfighting function, echelon) with confidence score distributions |
| 4. Retrieval | Three-mode comparison: raw embeddings vs. ADC hybrid vs. full KD pipeline with taxonomy filters |
| 5. CODEX | Deterministic doctrinal evaluation with causal chain traces and principled abstention |
| 6. Benchmarks | NDCG@10, MRR, Precision@5 across all three retrieval modes |
| 7. Package | Portable KD export: schema, config, benchmarks, manifest -- the flywheel artifact |

## Benchmark Results

| Configuration | NDCG@10 | MRR | Precision@5 |
|---------------|---------|-----|-------------|
| Raw embeddings | 0.2714 | 0.2721 | 0.1111 |
| ADC (hybrid search) | 0.2785 | 0.2814 | 0.1111 |
| Full pipeline (with taxonomy filters) | 0.2920 | 0.3127 | 0.1185 |

The full pipeline beats raw embeddings by +7.6% NDCG@10 and +14.9% MRR. ADC structure alone accounts for +2.6% NDCG@10; semantic lifting and taxonomy filtering add the rest.

## Technical Notes

- **Embeddings:** all-MiniLM-L6-v2 (384 dims) for the prototype. Production target is text-embedding-3-large (1024 dims).
- **LLM:** Claude Sonnet for lifting and CODEX compilation. The evaluation path is deterministic (no LLM).
- **CODEX objects:** Pre-compiled from all 5 source documents. The rule engine evaluates causal chains, preconditions, constraints, and doctrinal coherence without any LLM calls.
- **Benchmark Q/A:** 15 questions with paragraph-ID ground truth spanning 5 documents.
- **Data:** All data in this demo is a snapshot from a live pipeline. The full prototype runs against PostgreSQL/pgvector with real-time hybrid search and live embedding.
