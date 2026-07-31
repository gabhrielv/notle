"""Tests for the table the feed reads.

What matters here is that the row a request will divide by was measured the same
way the request weighs its profile, and that the window is a window.
"""

import json
import math
from datetime import UTC, datetime

from ingest.candidates import TOP_TERMS, build, materialize, read_window
from ranking.vectors import norm, weigh
from tests.test_pipeline import FakeClient

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


def row(cluster_id, term, tf, published_at="2026-07-31T12:00:00Z"):
    return {"cluster_id": cluster_id, "term": term, "tf": tf, "published_at": published_at}


class TestBuild:
    def test_one_row_per_cluster(self):
        rows = [row(1, "selic", 0.5), row(1, "copom", 0.5), row(2, "futebol", 1.0)]

        built = build(rows, {}, total_docs=311, now=NOW)

        assert {candidate[0] for candidate in built} == {1, 2}

    def test_the_norm_matches_what_weighing_the_cluster_gives(self):
        """The number a request divides by.

        If this drifted from `ranking.vectors`, nothing would raise. The feed
        would come back plausibly ordered and quietly wrong, which is why the
        two sides share one definition rather than agreeing by convention.
        """
        counts = {"selic": 4, "governo": 200}
        rows = [row(1, "selic", 0.7), row(1, "governo", 0.3)]

        built = build(rows, counts, total_docs=311, now=NOW)

        expected = norm(weigh({"selic": 0.7, "governo": 0.3}, counts, 311))
        assert math.isclose(built[0][2], expected)

    def test_a_cluster_of_terms_the_whole_corpus_uses_is_dropped(self):
        """Every term in every document means every weight is zero.

        The row would divide to an affinity of zero against every profile that
        will ever exist, so storing it can only cost a scan.
        """
        rows = [row(1, "governo", 1.0)]

        assert build(rows, {"governo": 311}, total_docs=311, now=NOW) == []

    def test_the_base_score_falls_with_age(self):
        fresh = build([row(1, "selic", 1.0, "2026-07-31T12:00:00Z")], {}, 311, NOW)
        stale = build([row(2, "selic", 1.0, "2026-07-30T12:00:00Z")], {}, 311, NOW)

        assert fresh[0][1] > stale[0][1]

    def test_top_terms_are_the_heaviest_and_are_readable_json(self):
        """The card shows these to a person, so they travel as words.

        Accents survive rather than becoming escapes, because the column is read
        by a human as often as by a parser.
        """
        counts = {"eleição": 3, "governo": 250, "país": 260}
        rows = [row(1, "eleição", 0.4), row(1, "governo", 0.3), row(1, "país", 0.3)]

        built = build(rows, counts, total_docs=311, now=NOW)

        assert json.loads(built[0][4])[0] == "eleição"

    def test_top_terms_are_capped(self):
        rows = [row(1, f"termo{i}", 0.1) for i in range(20)]

        built = build(rows, {}, total_docs=311, now=NOW)

        assert len(json.loads(built[0][4])) == TOP_TERMS


class TestReadWindow:
    def test_asks_for_two_days(self):
        client = FakeClient(rows=[])

        read_window(client, NOW)

        assert client.params_matching("FROM clusters c") == [["2026-07-29T12:00:00Z"]]


class TestMaterialize:
    def test_the_table_is_replaced_not_appended_to(self):
        """The window slides every hour, so most of what changes is which rows
        belong at all. Leaving yesterday's rows behind would show a reader
        stories the feed had already aged out.
        """
        client = FakeClient()

        materialize(client, [(1, 0.9, 2.0, "2026-07-31T12:00:00Z", "[]")])

        assert any("DELETE FROM feed_candidates" in sql for sql in client.queries)
        assert client.rows_written("feed_candidates") == [
            (1, 0.9, 2.0, "2026-07-31T12:00:00Z", "[]")
        ]
