"""Tests for regrouping a corpus that was stored before clustering existed.

The matching itself is covered in test_clustering.py. What is specific here is
that the pass walks an archive rather than one hourly batch, so it has to expire
its own anchors instead of getting the window from a WHERE clause.

`document_counts` is empty and `total_docs` is fixed, which gives every term the
same IDF and leaves the cosine comparing raw frequencies. These tests are about
which articles end up together, not about which words the corpus finds rare.
"""

from scripts.backfill_clusters import regroup

TOTAL_DOCS = 311


def article(article_id: int, published_at: str) -> dict:
    """An article as the corpus holds it today: alone in a cluster of its own."""
    return {"id": article_id, "cluster_id": article_id, "published_at": published_at}


SELIC = {"copom": 0.25, "selic": 0.25, "manter": 0.25, "juro": 0.25}


class TestRegroup:
    def test_the_same_story_lands_in_one_cluster(self):
        articles = [article(1, "2026-07-31T09:00:00Z"), article(2, "2026-07-31T09:20:00Z")]
        vectors = {1: SELIC, 2: {"copom": 0.3, "selic": 0.3, "manter": 0.2, "taxa": 0.2}}

        assignment = regroup(articles, vectors, {}, TOTAL_DOCS)

        assert assignment[1] == assignment[2]

    def test_the_group_keeps_the_cluster_of_its_oldest_article(self):
        """Reusing an id rather than allocating one keeps the write small.

        Only the articles that move are updated, and the clusters left behind
        are the ones to delete.
        """
        articles = [article(1, "2026-07-31T09:00:00Z"), article(2, "2026-07-31T09:20:00Z")]
        vectors = {1: SELIC, 2: dict(SELIC)}

        assignment = regroup(articles, vectors, {}, TOTAL_DOCS)

        assert assignment == {1: 1, 2: 1}

    def test_an_unrelated_story_keeps_its_own_cluster(self):
        articles = [article(1, "2026-07-31T09:00:00Z"), article(2, "2026-07-31T09:20:00Z")]
        vectors = {1: SELIC, 2: {"grêmio": 0.5, "sul-americana": 0.5}}

        assignment = regroup(articles, vectors, {}, TOTAL_DOCS)

        assert assignment == {1: 1, 2: 2}

    def test_a_cluster_older_than_the_window_cannot_capture_anything(self):
        """The ingestion gets this from `first_seen_at >= ?`; a backfill does not.

        Without expiry, a pass over months of archive would compare every
        article against every cluster ever opened, and the same recurring
        subject would collapse a year of coverage into one card.
        """
        articles = [article(1, "2026-07-29T09:00:00Z"), article(2, "2026-07-31T09:00:00Z")]
        vectors = {1: SELIC, 2: dict(SELIC)}

        assignment = regroup(articles, vectors, {}, TOTAL_DOCS)

        assert assignment[1] != assignment[2]

    def test_the_window_is_measured_from_the_anchor_not_from_the_run(self):
        """Two days of coverage chain only if each link is inside a day of the last.

        Here the middle article is within a day of the first and the last is
        within a day of the middle, but the anchor never moves, so the last one
        is compared against the first and falls outside.
        """
        articles = [
            article(1, "2026-07-29T09:00:00Z"),
            article(2, "2026-07-30T05:00:00Z"),
            article(3, "2026-07-31T01:00:00Z"),
        ]
        vectors = {1: SELIC, 2: dict(SELIC), 3: dict(SELIC)}

        assignment = regroup(articles, vectors, {}, TOTAL_DOCS)

        assert assignment[1] == assignment[2]
        assert assignment[3] != assignment[1]

    def test_an_article_without_terms_keeps_the_cluster_it_had(self):
        """Nothing in the corpus should have an empty vector, since `prepare`
        drops those before they are stored. Reading the archive is not the place
        to discover that one slipped through and lose its row over it.
        """
        articles = [article(1, "2026-07-31T09:00:00Z"), article(2, "2026-07-31T09:20:00Z")]

        assignment = regroup(articles, {1: SELIC}, {}, TOTAL_DOCS)

        assert assignment[2] == 2

    def test_running_twice_changes_nothing(self):
        """The script is meant to be safe to re-run after a partial failure."""
        articles = [
            article(1, "2026-07-31T09:00:00Z"),
            article(2, "2026-07-31T09:20:00Z"),
            article(3, "2026-07-31T09:40:00Z"),
        ]
        vectors = {1: SELIC, 2: dict(SELIC), 3: {"grêmio": 0.5, "sul-americana": 0.5}}

        first = regroup(articles, vectors, {}, TOTAL_DOCS)
        regrouped = [{**a, "cluster_id": first[a["id"]]} for a in articles]

        assert regroup(regrouped, vectors, {}, TOTAL_DOCS) == first
