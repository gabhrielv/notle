"""Tests for removing terms nobody will compare against again.

What is pinned here is the rule that keeps the promise from breaking the
product. The architecture said to prune beyond the ranking window, and the
ranking window is 48 hours; implemented literally that would delete the terms a
reader's own profile is rebuilt from.
"""

from ingest import prune


class FakeClient:
    """Records the statements it was given and answers the count with a number."""

    def __init__(self, pending=0):
        self.pending = pending
        self.statements = []

    def query(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), list(params or [])))
        if sql.strip().startswith("SELECT COUNT"):
            return [{"n": self.pending}]
        return []


class TestProtection:
    """The half of the rule that stops the profile from shrinking on its own."""

    def test_an_anchor_of_an_answered_cluster_is_never_removed(self):
        """`signal_vectors` rebuilds a reader's taste by joining article_terms on
        the anchor of every cluster they answered. Deleting those would mean a
        like from Tuesday losing its vector on Thursday, with nothing on screen
        to point at.
        """
        client = FakeClient(pending=5)
        prune.run(client, "2026-05-05T00:00:00Z")

        delete = next(sql for sql, _ in client.statements if sql.startswith("DELETE"))

        assert "representative_article_id" in delete
        assert "FROM interactions" in delete
        assert "NOT IN" in delete

    def test_the_protection_is_evaluated_by_the_database(self):
        """Reading the ids out and binding them back would run into the hundred
        parameter ceiling, and a reader with a long history would silently stop
        being protected past the cap.
        """
        client = FakeClient(pending=5)
        prune.run(client, "2026-05-05T00:00:00Z")

        _, params = next((s, p) for s, p in client.statements if s.startswith("DELETE"))

        assert params == ["2026-05-05T00:00:00Z"]


class TestRetention:
    def test_it_outlasts_the_long_profile_s_own_half_life(self):
        """Sixty days is the half life of a signal in the long profile, so a
        signal still worth more than a third of its weight must never find its
        terms missing.
        """
        from api import profile

        assert prune.RETENTION_DAYS > profile.LONG_HALF_LIFE_DAYS

    def test_it_is_not_the_ranking_window(self):
        """Three things read this table and only one is the feed. Clustering
        looks back a day, co-occurrence reads everything, and the profile reaches
        as far back as the reader's own history.
        """
        assert prune.RETENTION_DAYS > 2


class TestRun:
    def test_nothing_to_prune_issues_no_delete(self):
        """A weekly job on a young corpus should cost one count and nothing
        else, rather than a delete that scans two tables to remove zero rows.
        """
        client = FakeClient(pending=0)

        assert prune.run(client, "2026-05-05T00:00:00Z") == 0
        assert not any(sql.startswith("DELETE") for sql, _ in client.statements)

    def test_it_reports_what_it_removed(self):
        client = FakeClient(pending=166)

        assert prune.run(client, "2026-05-05T00:00:00Z") == 166

    def test_counting_never_deletes(self):
        client = FakeClient(pending=166)

        assert prune.plan(client, "2026-05-05T00:00:00Z") == 166
        assert not any(sql.startswith("DELETE") for sql, _ in client.statements)
