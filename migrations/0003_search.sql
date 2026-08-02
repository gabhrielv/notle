-- Full text search over the corpus.
--
-- A LIKE over title and summary would have needed no migration, but it scans
-- the whole archive on every keystroke, and D1 bills rows read including the
-- ones the WHERE throws away. That is the same constraint that made the
-- inverted index mandatory for ranking; a search that ignores it would grow
-- more expensive every hour the ingestion runs.
--
-- `remove_diacritics 2` is the reason this is FTS5 rather than the lemma index.
-- Search is typed by a person, and a person types `eleicao` as often as
-- `eleição`. The lemma index cannot help there: matching a query against lemmas
-- would require lemmatizing the query, and spaCy does not run inside a Worker.
-- Folding diacritics at tokenization solves it on both sides at once, for the
-- stored text and for what was typed.
--
-- Standalone rather than `content='articles'`. External content would save the
-- copy of title and summary, at the cost of either triggers or a rebuild that
-- has to stay in step with an ingestion that writes in batches over HTTP. The
-- duplicated text is title and a summary capped at 600 characters, which is
-- small next to article_terms, and the ingestion already knows the article ids
-- at the point it would write here.
CREATE VIRTUAL TABLE article_search USING fts5(
    title,
    summary,
    tokenize = "unicode61 remove_diacritics 2"
);
