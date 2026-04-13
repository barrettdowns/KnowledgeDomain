-- Prototype adaptation: 384 dimensions (all-MiniLM-L6-v2).
-- Production uses 1024 dimensions (text-embedding-3-large).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE kd_doctrine (
    record_id           UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    source_document     VARCHAR(512)    NOT NULL,
    source_system       VARCHAR(256),
    ingestion_timestamp TIMESTAMPTZ     NOT NULL DEFAULT now(),
    classification      VARCHAR(64)     NOT NULL,
    provenance          VARCHAR(512),

    -- ADC chunk metadata (deterministic, populated at ingestion)
    chunk_content       TEXT            NOT NULL,
    paragraph_id        VARCHAR(128)    NOT NULL,
    hierarchy_path      JSONB           NOT NULL,
    modality            VARCHAR(32)     NOT NULL,
    modality_confidence FLOAT,
    modality_signals    JSONB,
    glossary_refs       JSONB,
    acronym_refs        JSONB,
    document_type       VARCHAR(128),
    page_start          INTEGER,
    page_end            INTEGER,

    -- Vector data (384 dims for prototype)
    primary_embedding   vector(384)     NOT NULL,

    -- Semantic lifting (populated by lifting pipeline, NULL until lifted)
    warfighting_function            VARCHAR(128),
    warfighting_function_confidence FLOAT,
    echelon                         VARCHAR(128),
    echelon_confidence              FLOAT,
    doctrinal_phase                 VARCHAR(128),
    doctrinal_phase_confidence      FLOAT,
    document_type_lifted            VARCHAR(128),
    document_type_lifted_confidence FLOAT,

    custom_metadata     JSONB           DEFAULT '{}'::jsonb,
    lift_model_version  VARCHAR(128),
    lift_timestamp      TIMESTAMPTZ,

    -- Full-text search
    content_fts         TSVECTOR        GENERATED ALWAYS AS (
                            to_tsvector('english', chunk_content)
                        ) STORED
);

-- Vector index
CREATE INDEX idx_kd_doctrine_embedding
    ON kd_doctrine USING hnsw (primary_embedding vector_cosine_ops);

-- Metadata indexes
CREATE INDEX idx_kd_doctrine_modality ON kd_doctrine (modality);
CREATE INDEX idx_kd_doctrine_paragraph_id ON kd_doctrine (paragraph_id);
CREATE INDEX idx_kd_doctrine_source_document ON kd_doctrine (source_document);
CREATE INDEX idx_kd_doctrine_hierarchy_path ON kd_doctrine USING gin (hierarchy_path);

-- Taxonomy indexes
CREATE INDEX idx_kd_doctrine_wf ON kd_doctrine (warfighting_function) WHERE warfighting_function IS NOT NULL;
CREATE INDEX idx_kd_doctrine_echelon ON kd_doctrine (echelon) WHERE echelon IS NOT NULL;
CREATE INDEX idx_kd_doctrine_phase ON kd_doctrine (doctrinal_phase) WHERE doctrinal_phase IS NOT NULL;

-- Full-text search index
CREATE INDEX idx_kd_doctrine_fts ON kd_doctrine USING gin (content_fts);

-- Lifting provenance
CREATE INDEX idx_kd_doctrine_lift ON kd_doctrine (lift_model_version, lift_timestamp)
    WHERE lift_model_version IS NOT NULL;
