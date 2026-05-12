# Local Nexus setup for LIVE-mode operation

This document captures the procedure to stand up a local Nexus + Prefect + Ollama + pgvector-rag stack so the Streamlit app can run in **LIVE** mode (talking to real `/kd/...` endpoints) rather than the default **LOCAL** mode (in-process fallback).

**Status:** Not yet executed. Side-effects (image pulls, model downloads measured in gigabytes, docker container lifecycle, license-file mounting) should be triggered intentionally during a maintenance window rather than silently from an agent session. The plan and app work fully in LOCAL mode without any of this; LIVE mode is an optional upgrade.

## Prerequisites

| Item | Where it lives | Verified? |
|---|---|---|
| Valid `perpetual.license` file | mounted into `nexus-service` container at `/app/license.bin` | not yet |
| Ollama installed locally on host | `https://ollama.ai/` | not yet |
| `qwen3.5:9b` chat model | `ollama pull qwen3.5:9b` (~5 GB) | not yet |
| `mxbai-embed-large:335m-v1-fp16` embedding model | `ollama pull mxbai-embed-large:335m-v1-fp16` (~670 MB) | not yet |
| Docker / Docker Compose running | `docker info` returns clean | not yet |
| `/Users/barrettdowns/Projects/nexus/` checked out, `develop` branch | `cd /Users/barrettdowns/Projects/nexus && git status` | confirmed (May 12) |
| Sibling `nexus-prefect-flows/` repo (for `pgvector-rag`) | `/Users/barrettdowns/Projects/nexus-prefect-flows/` | unknown |

## Setup procedure

These commands assume you have the prerequisites above. Do not paste them blindly — review each step.

### 1. Re-instate the full Prefect stack in nexus/docker-compose

The committed `nexus/docker-compose.yml` is the stripped version (only `nexus-service`). The `README.DEV.md` Quickstart instructions describe re-adding `prefect-server`, `prefect-services`, `prefect-worker`, `postgres`, `redis`. We do this in a **non-destructive copy** so we never commit a modified compose to the Nexus repo.

```bash
cd /Users/barrettdowns/Projects/nexus
cp docker-compose.yml docker-compose.full.yml
# Edit docker-compose.full.yml: re-add prefect-server, prefect-services,
# prefect-worker, postgres, redis services per README.DEV.md Quickstart.
# Reference: README.DEV.md "Option 1: Docker Compose (Recommended for Development)"
```

`docker-compose.full.yml` is **not committed** to the Nexus repo. It stays local-only.

### 2. Override env to use Ollama backends

Do **not** modify the committed `docker.env`. Create a `.env` override:

```bash
cd /Users/barrettdowns/Projects/nexus
cat > .env <<'EOF'
CHAT_BACKEND=ollama
CHAT_ENDPOINT=http://host.docker.internal:11434
CHAT_MODEL=qwen3.5:9b

SEARCH_CHAT_BACKEND=ollama
SEARCH_CHAT_ENDPOINT=http://host.docker.internal:11434
SEARCH_CHAT_MODEL=qwen3.5:9b

EMBEDDING_BACKEND=ollama
EMBEDDING_ENDPOINT=http://host.docker.internal:11434
EMBEDDING_MODEL=mxbai-embed-large:335m-v1-fp16
PGVECTOR_DATABASE_URI=postgresql://rag:rag@pgvector-rag:5432/rag
PGVECTOR_TABLE=prefect_flows.document_chunks
EOF
```

### 3. Place the license file

```bash
cp /path/to/perpetual.license /Users/barrettdowns/Projects/nexus/perpetual.license
chmod 600 /Users/barrettdowns/Projects/nexus/perpetual.license
```

### 4. Bring up pgvector-rag (separate compose)

```bash
# If the sibling repo exists:
cd /Users/barrettdowns/Projects/nexus-prefect-flows
docker compose up -d pgvector-rag

# If it does NOT exist, run an equivalent ad-hoc container:
docker run -d --name pgvector-rag \
  --network nexus-dev-net \
  -p 5433:5432 \
  -e POSTGRES_USER=rag -e POSTGRES_PASSWORD=rag -e POSTGRES_DB=rag \
  pgvector/pgvector:pg16
```

### 5. Initialize pgvector-rag schema

```bash
cd /Users/barrettdowns/Projects/nexus
docker exec -i pgvector-rag psql -U rag -d rag < scripts/setup_pgvector_test.sql
```

### 6. Bring up Nexus + Prefect + Redis

```bash
cd /Users/barrettdowns/Projects/nexus
docker compose -f docker-compose.full.yml --env-file .env up -d
```

Wait ~30 seconds for services to settle.

## Validation: legacy surface (always present)

These should all return 200 / produce output:

```bash
# Help endpoint
curl -fsS http://localhost:49180/nexus-service/help/
# Returns: {"statusMsg": "Knowledge Domains", ...}

# Legacy A2A search (vector-only against pgvector-rag's document_chunks)
curl -fsS -X POST http://localhost:49180/nexus-service/a2a/search-agent \
  -H 'Content-Type: application/json' \
  -d '{"query":"operational art","top_k":5}'
# Returns: KnowledgeBaseQueryResponse-shaped hits or empty if corpus not seeded

# Trivial Prefect run (assumes prefect_example.py is registered)
curl -fsS -X POST http://localhost:49180/nexus-service/run/ \
  -H 'Content-Type: application/json' \
  -d '{"deploymentName":"my-first-deployment/main"}'
# Returns: {"token":"...", "flowRunId":"...", "status":"PENDING", ...}
```

## Validation: RFC-0001 /kd/... routes (per-route probe)

This is the **Phase 1 route-availability matrix**. Record 200 vs 404 vs other for each route into the table below. Downstream phases' LIVE-mode acceptance criteria gate per-route on this.

```bash
# Set environment ids (these must match Phase 2's env knobs)
export NEXUS_KD_ID=kd-doctrine
export NEXUS_KB_ID_DOCTRINE_NAIVE=kb-doctrine-naive
export NEXUS_KB_ID_DOCTRINE_MOAT=kb-doctrine-moat

# Probe 1: KB query (read)
curl -sS -o /tmp/probe1.json -w "HTTP %{http_code}\n" \
  -X POST "http://localhost:49180/nexus-service/kd/knowledge-bases/${NEXUS_KB_ID_DOCTRINE_NAIVE}/query" \
  -H 'Content-Type: application/json' \
  -d '{"query":"operational art","top_k":3,"projection_kinds":["text"]}'

# Probe 2: KB runs (ingest enqueue)
curl -sS -o /tmp/probe2.json -w "HTTP %{http_code}\n" \
  -X POST "http://localhost:49180/nexus-service/kd/knowledge-bases/${NEXUS_KB_ID_DOCTRINE_NAIVE}/runs" \
  -H 'Content-Type: application/json' \
  -d '{"blob_uri":"file:///tmp/nonexistent","parameters":{"dry_run":true}}'

# Probe 3: KD bundle import
curl -sS -o /tmp/probe3.json -w "HTTP %{http_code}\n" \
  -X POST "http://localhost:49180/nexus-service/kd/knowledge-domains/from-yaml" \
  -H 'Content-Type: text/yaml' \
  --data-binary "version: 1
kind: KnowledgeDomainBundle
knowledgeDomain:
  id: probe-only
  name: probe
  knowledge_base_ids: []
  model: none
  backend: none
knowledgeBases: []
skillSets: []
indexers: []
indices: []"

# Probe 4: KD chat
curl -sS -o /tmp/probe4.json -w "HTTP %{http_code}\n" \
  -X POST "http://localhost:49180/nexus-service/kd/knowledge-domains/${NEXUS_KD_ID}/agent/messages" \
  -H 'Content-Type: application/json' \
  -d '{"message":"hello"}'

# Probe 5: completion proxy (for Phase 8)
curl -sS -o /tmp/probe5.json -w "HTTP %{http_code}\n" \
  -X POST "http://localhost:49180/nexus-service/complete" \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"hi"}]}'
```

### Route availability matrix (fill in after probing)

| Route | HTTP status | Implemented? | Notes |
|---|---|---|---|
| `POST /kd/knowledge-bases/{kb_id}/query` | _to record_ | _to record_ | RFC-0001 §1.6.5.6.1 |
| `POST /kd/knowledge-bases/{kb_id}/runs` | _to record_ | _to record_ | RFC-0001 §1.6.5.6.2 |
| `POST /kd/knowledge-domains/from-yaml` | _to record_ | _to record_ | RFC-0001 §1.6.5.10 |
| `POST /kd/knowledge-domains/{kd_id}/agent/messages` | _to record_ | _to record_ | RFC-0001 §1.6.5.8 |
| `POST /complete` | _to record_ | _to record_ | Legacy Nexus completion proxy (predates RFC-0001) |

A 404 on any `/kd/...` row is **expected if Nexus hasn't yet implemented the RFC** — that's a per-route signal, not a setup failure. The Streamlit app's LIVE mode reads this matrix and falls back to LOCAL behavior on a per-route basis. Phase 2's `nexus_client.py` also keeps a legacy `/a2a/search-agent` wrapper as a final fallback for retrieval.

## Teardown

```bash
cd /Users/barrettdowns/Projects/nexus
docker compose -f docker-compose.full.yml down

cd /Users/barrettdowns/Projects/nexus-prefect-flows  # or the ad-hoc container
docker compose down                                    # or: docker rm -f pgvector-rag
```

## Why this is deferred

Side-effects this procedure has on your machine that an agent session should not silently trigger:
- Pulling ~6 GB of Ollama models
- Starting and leaving running long-lived Docker containers
- Mounting a license file
- Modifying the docker-network state

When you're ready to run LIVE mode, work through this doc top-to-bottom and fill in the route availability matrix. The Streamlit app will pick up `NEXUS_API_URL=http://localhost:49180/nexus-service` automatically and the sidebar will show "LIVE (Nexus reachable)" once `/help/` returns 200.
