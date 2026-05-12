-- Phase 3: naive SkillSet projection table.
--
-- Backs the text_chunks IndexProjection of idx-doctrine-naive (catalog/doctrine-naive.yaml).
-- Mirrors RFC-0001 §1.6.4 IndexProjection shape: parent_key_field is section_id
-- (filterable per RFC-0001 §1.6.4 invariant; required if include_siblings=true is
-- ever requested against this projection — see Phase 6 stretch goal).
--
-- 384-d to match the moat projection's embedding dim — the A/B isolates SkillSet
-- and field schema as the variables, not the embedding model.

CREATE TABLE IF NOT EXISTS doctrine_naive_text_chunks (
    chunk_id       VARCHAR(256)  PRIMARY KEY,
    section_id     VARCHAR(256),                                       -- parent_key_field (filterable)
    source_uri     VARCHAR(512),
    source_document VARCHAR(512),
    chunk_index    INTEGER,
    content        TEXT          NOT NULL,
    content_vector vector(384)   NOT NULL,
    content_fts    TSVECTOR      GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    ingested_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- Vector ANN index (IVFFlat; HNSW would be a future tuning step)
CREATE INDEX IF NOT EXISTS doctrine_naive_text_chunks_vec_idx
    ON doctrine_naive_text_chunks
    USING ivfflat (content_vector vector_cosine_ops) WITH (lists = 100);

-- Lexical index for hybrid retrieval
CREATE INDEX IF NOT EXISTS doctrine_naive_text_chunks_fts_idx
    ON doctrine_naive_text_chunks
    USING GIN (content_fts);

-- Filter index on parent_key_field (RFC-0001 §1.6.4: parent_key_field must be filterable
-- so include_siblings=true against this projection is a valid query)
CREATE INDEX IF NOT EXISTS doctrine_naive_text_chunks_section_idx
    ON doctrine_naive_text_chunks (section_id);

-- Filter index by source document (useful for the Streamlit "browse" panel)
CREATE INDEX IF NOT EXISTS doctrine_naive_text_chunks_source_idx
    ON doctrine_naive_text_chunks (source_document);
