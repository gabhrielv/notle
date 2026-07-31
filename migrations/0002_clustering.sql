-- Slice 2 stops the feed repeating the same story across portals.
--
-- The schema already carried the shape: every article had a cluster and
-- clusters.representative_article_id was reserved but never filled. What
-- changes is that the column now holds the article whose vector the group is
-- matched against, and that ingestion asks for the clusters of the last 24
-- hours on every run.
--
-- Without this index that question is a full scan of clusters. D1 bills rows
-- read including the ones the WHERE discards, so the scan would grow with the
-- whole archive while the answer stays roughly the size of one day.

CREATE INDEX idx_clusters_first_seen ON clusters(first_seen_at);
