-- Notle, slice 1 schema.
--
-- Two choices here are load bearing and documented in docs/ARQUITETURA.md:
--
--   article_terms stores raw TF, never TF-IDF. IDF is a function of the whole
--   corpus and shifts on every ingestion run, so materializing it would leave
--   old articles measured on a different ruler than fresh ones.
--
--   Every article gets a cluster, even when it is alone in it. Slice 2 only
--   swaps the function that picks the cluster; nothing above it changes.

CREATE TABLE sources (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    feed_url     TEXT NOT NULL UNIQUE,
    homepage_url TEXT NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL
);

CREATE TABLE clusters (
    id                        INTEGER PRIMARY KEY,
    representative_article_id INTEGER,
    first_seen_at             TEXT NOT NULL,
    size                      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE articles (
    id           INTEGER PRIMARY KEY,
    source_id    INTEGER NOT NULL REFERENCES sources(id),
    cluster_id   INTEGER REFERENCES clusters(id),
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL UNIQUE,
    published_at TEXT NOT NULL,
    fetched_at   TEXT NOT NULL
);

CREATE INDEX idx_articles_cluster ON articles(cluster_id);
CREATE INDEX idx_articles_published ON articles(published_at);

CREATE TABLE terms (
    term      TEXT PRIMARY KEY,
    doc_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE corpus_stats (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    total_docs INTEGER NOT NULL DEFAULT 0
);

INSERT INTO corpus_stats (id, total_docs) VALUES (1, 0);

CREATE TABLE article_terms (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    term       TEXT NOT NULL,
    tf         REAL NOT NULL,
    PRIMARY KEY (article_id, term)
);

-- The inverted index, and the single most important line in this file. Ranking
-- sends the strongest profile terms and touches only articles that share one of
-- them, so the work is proportional to the overlap and not to the archive. D1
-- bills scanned rows, including the ones the WHERE throws away, which turns
-- this from an optimization into a cost constraint.
CREATE INDEX idx_article_terms_term ON article_terms(term);

CREATE TABLE users (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    discovery_ratio REAL NOT NULL DEFAULT 0.15
);

CREATE TABLE interactions (
    id          INTEGER PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    article_id  INTEGER REFERENCES articles(id),
    cluster_id  INTEGER,
    session_id  TEXT,
    type        TEXT NOT NULL,
    value       REAL,
    duration_ms INTEGER,
    created_at  TEXT NOT NULL
);

-- Slice 1 reads this to exclude hidden clusters. Slice 3 reads the same rows
-- with a different lens to build the negative vector, and slice 6 reads them
-- again filtered by session_id. Interactions are events, never flags.
CREATE INDEX idx_interactions_user_type ON interactions(user_id, type);

CREATE TABLE user_profile (
    user_id         TEXT PRIMARY KEY REFERENCES users(id),
    term_vector     TEXT NOT NULL DEFAULT '{}',
    neg_term_vector TEXT NOT NULL DEFAULT '{}',
    updated_at      TEXT NOT NULL
);

-- Materialized by the ingestion job, one row per candidate cluster in the
-- ranking window. norm is the length of the cluster vector under the IDF of the
-- moment it was written, which is what lets the request divide for the cosine
-- without touching every term of every document.
CREATE TABLE feed_candidates (
    cluster_id   INTEGER PRIMARY KEY REFERENCES clusters(id),
    base_score   REAL NOT NULL,
    norm         REAL NOT NULL,
    published_at TEXT NOT NULL,
    top_terms    TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX idx_feed_candidates_published ON feed_candidates(published_at);
