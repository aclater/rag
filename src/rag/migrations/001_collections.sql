-- rag's own tables. Llama Stack owns its vector-store tables in the same
-- database; these hold what rag needs on top: which embedding model each
-- collection is bound to, which corpus revision is indexed, and the full text
-- of each source section for the fetch tool.

CREATE TABLE IF NOT EXISTS rag_collection (
    name              text PRIMARY KEY,
    vector_store_id   text NOT NULL UNIQUE,
    embedding_model   text NOT NULL,
    embedding_dim     integer NOT NULL CHECK (embedding_dim > 0),
    source            text NOT NULL,
    corpus_version    text NOT NULL,
    description       text NOT NULL DEFAULT '',
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_section (
    collection     text NOT NULL REFERENCES rag_collection(name) ON DELETE CASCADE,
    section        text NOT NULL,
    title          text NOT NULL,
    parent         text,
    source_url     text NOT NULL,
    corpus_version text NOT NULL,
    content_hash   text NOT NULL,
    body           text NOT NULL,
    chunk_ids      text[] NOT NULL DEFAULT '{}',
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (collection, section)
);
