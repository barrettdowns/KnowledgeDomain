# KD Platform -- Guided Tour

Interactive demo of the Knowledge Domain platform architecture. Seven tabs walk through the end-to-end system: domain-specific chunking (ADC), semantic lifting with confidence scores, hybrid retrieval with metadata filtering, deterministic doctrinal evaluation (CODEX), benchmark infrastructure, and reusable KD packaging.

Built against 5 Army doctrine documents (ADP 3-0, FM 2-0, FM 3-12, FM 3-61, FM 5-0). 2,910 chunks, fully lifted, with modality classification, warfighting function extraction, echelon tagging, and confidence scores.

## Run Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Tabs

| Tab | What It Shows |
|-----|---------------|
| 1. The Problem | Side-by-side: commodity 5-column schema vs. 30+ column KD schema |
| 2. ADC | Deterministic chunking with hierarchy, modality, glossary linkage -- zero LLM calls |
| 3. Semantic Lifting | LLM-extracted domain fields (warfighting function, echelon) with confidence scores |
| 4. Retrieval | Three-mode comparison: raw embeddings vs. ADC hybrid vs. full KD pipeline |
| 5. CODEX | Deterministic doctrinal evaluation -- SUPPORTED / CONDITIONAL / ABSTAIN |
| 6. Benchmarks | NDCG@10, MRR, Precision@5 across retrieval modes |
| 7. Package | Portable KD export: schema, config, benchmarks, manifest |
