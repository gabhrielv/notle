"""Tests for the request side.

The database paths were exercised end to end against the real D1 through
`wrangler dev`, which is a stronger check than a mock of the binding would be.
What is pinned here is the logic that turns rows into a feed and headers into a
visitor, because that is where a mistake is silent rather than loud.

Async functions are driven with `asyncio.run` instead of a pytest plugin: two
call sites do not justify a dependency, and the Worker bundle is meant to stay
free of them anyway.
"""

import asyncio
from datetime import UTC, datetime

from api import feed, profile, users

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


class FakeEnv:
    """Replays canned rows for whichever statement asks for them."""

    def __init__(self, rows_by_sql=None):
        self.rows_by_sql = rows_by_sql or {}
        self.calls = []


async def fake_query(env, sql, params=None):
    """Stands in for `api.db.query`, which takes the binding as its first argument."""
    env.calls.append((sql, list(params or [])))
    for fragment, rows in env.rows_by_sql.items():
        if fragment in sql:
            return rows
    return []


def patched(monkeypatch, env):
    """Points the module level `query` at the fake for the duration of a test."""
    monkeypatch.setattr(profile, "query", fake_query)
    monkeypatch.setattr(feed, "query", fake_query)
    return env


class TestReadCookie:
    def test_finds_our_value_among_others(self):
        assert users.read_cookie("theme=dark; nid=abc; lang=pt") == "abc"

    def test_no_header_at_all(self):
        assert users.read_cookie(None) is None

    def test_a_header_without_our_cookie(self):
        assert users.read_cookie("theme=dark") is None

    def test_a_cookie_whose_name_merely_ends_with_ours(self):
        """`partition` splits on the first `=`, so the name has to match whole.

        A prefix match would let `xnid=` be read as ours and hand the reader
        somebody else's profile.
        """
        assert users.read_cookie("xnid=abc") is None

    def test_an_empty_value_is_not_an_identity(self):
        assert users.read_cookie("nid=") is None


class TestSetCookie:
    def test_carries_the_attributes_that_matter(self):
        header = users.set_cookie("db0e65d3-bdba-4abd-9c29-ea4522dbecec")

        assert "HttpOnly" in header
        assert "Secure" in header
        assert "SameSite=Lax" in header

    def test_not_samesite_strict(self):
        """The demo is a link people follow from somewhere else.

        Under Strict the cookie is withheld on that first cross site navigation,
        so every arrival from a link would be handed a brand new profile.
        """
        assert "SameSite=Strict" not in users.set_cookie("x")


class TestLooksLikeOurs:
    def test_accepts_what_we_issue(self):
        assert users.looks_like_ours("db0e65d3-bdba-4abd-9c29-ea4522dbecec")

    def test_rejects_junk_before_it_costs_a_round_trip(self):
        assert not users.looks_like_ours("' OR 1=1 --")
        assert not users.looks_like_ours("")
        assert not users.looks_like_ours(None)

    def test_rejects_a_uuid_written_another_way(self):
        """Round tripping through str() is what makes this exact.

        Braces and upper case parse fine but are not what we hand out, so
        accepting them would mean two spellings of one identity.
        """
        assert not users.looks_like_ours("DB0E65D3-BDBA-4ABD-9C29-EA4522DBECEC")


class TestCombine:
    def test_one_liked_cluster_is_its_own_vector(self):
        assert profile.combine([({"selic": 0.6, "copom": 0.4}, 1.0)]) == {
            "selic": 0.6,
            "copom": 0.4,
        }

    def test_two_likes_average_rather_than_accumulate(self):
        """A reader with forty likes must not carry a vector forty times longer.

        Length does not change the cosine, but it changes how a like compares
        against the recency floor, and the floor is a fixed number.
        """
        combined = profile.combine([({"selic": 1.0}, 1.0), ({"futebol": 1.0}, 1.0)])

        assert combined == {"selic": 0.5, "futebol": 0.5}

    def test_a_heavier_signal_pulls_harder(self):
        """A share says more than a like, and the table says how much more."""
        combined = profile.combine(
            [
                ({"selic": 1.0}, profile.WEIGHTS["like"]),
                ({"futebol": 1.0}, profile.WEIGHTS["share"]),
            ]
        )

        assert combined["futebol"] > combined["selic"]

    def test_nothing_liked_yet(self):
        assert profile.combine([]) == {}


class TestPositiveVectors:
    def test_groups_terms_by_the_cluster_they_came_from(self, monkeypatch):
        env = patched(
            monkeypatch,
            FakeEnv(
                {
                    "FROM interactions i": [
                        {"cluster_id": 1, "type": "like", "term": "selic", "tf": 0.6},
                        {"cluster_id": 1, "type": "like", "term": "copom", "tf": 0.4},
                        {"cluster_id": 2, "type": "share", "term": "futebol", "tf": 1.0},
                    ]
                }
            ),
        )

        vectors = asyncio.run(profile.positive_vectors(env, "u1"))

        assert sorted(vectors, key=lambda pair: pair[1]) == [
            ({"selic": 0.6, "copom": 0.4}, 1.0),
            ({"futebol": 1.0}, 1.5),
        ]

    def test_hide_is_not_a_positive_signal(self, monkeypatch):
        env = patched(monkeypatch, FakeEnv())

        asyncio.run(profile.positive_vectors(env, "u1"))

        _, params = env.calls[0]
        assert "hide" not in params


class TestRank:
    def rows(self):
        return [
            {
                "cluster_id": 1,
                "base_score": 1.0,
                "norm": 1.0,
                "published_at": "2026-07-31T12:00:00Z",
                "top_terms": '["selic"]',
            },
            {
                "cluster_id": 2,
                "base_score": 1.0,
                "norm": 1.0,
                "published_at": "2026-07-31T12:00:00Z",
                "top_terms": '["futebol"]',
            },
        ]

    def test_affinity_decides_between_two_stories_of_one_age(self):
        matched = {1: {"selic": 0.5}}

        ranked = feed.rank(self.rows(), matched, 1.0, set(), NOW)

        assert [card["cluster_id"] for card in ranked] == [1, 2]

    def test_a_cluster_already_answered_for_is_left_out(self):
        """Both halves of it.

        Hiding is the obvious one. Keeping matters for a subtler reason: the
        profile was built from that cluster's terms, so it matches itself better
        than anything else can and would pin itself to the top forever.
        """
        ranked = feed.rank(self.rows(), {1: {"selic": 0.5}}, 1.0, {1}, NOW)

        assert [card["cluster_id"] for card in ranked] == [2]

    def test_the_reason_is_the_terms_that_actually_contributed(self):
        matched = {1: {"selic": 0.5, "copom": 0.9, "juro": 0.1}}

        ranked = feed.rank(self.rows(), matched, 1.0, set(), NOW)

        assert ranked[0]["because"] == ["copom", "selic", "juro"]

    def test_a_card_nothing_matched_still_carries_a_score(self):
        """An empty profile is the common case, not an edge.

        Every card comes back with affinity zero and the recency floor orders
        them, so the first screen a visitor sees is ordered rather than tied.
        """
        ranked = feed.rank(self.rows(), {}, 0.0, set(), NOW)

        assert len(ranked) == 2
        assert all(card["score"] > 0 for card in ranked)
        assert all(card["because"] == [] for card in ranked)

    def test_a_page_is_capped(self):
        many = [
            {
                "cluster_id": i,
                "base_score": 1.0,
                "norm": 1.0,
                "published_at": "2026-07-31T12:00:00Z",
                "top_terms": "[]",
            }
            for i in range(feed.PAGE + 10)
        ]

        assert len(feed.rank(many, {}, 0.0, set(), NOW)) == feed.PAGE

    def test_top_terms_that_are_not_readable_json_do_not_take_the_feed_down(self):
        rows = self.rows()
        rows[0]["top_terms"] = "{nao e json"

        ranked = feed.rank(rows, {}, 0.0, set(), NOW)

        assert ranked[0]["about"] == []


class TestContributions:
    def test_folds_rows_into_cluster_then_term(self, monkeypatch):
        env = patched(
            monkeypatch,
            FakeEnv(
                {
                    "GROUP BY f.cluster_id, t.term": [
                        {"cluster_id": 1, "term": "selic", "contribution": 0.4},
                        {"cluster_id": 1, "term": "copom", "contribution": 0.2},
                        {"cluster_id": 2, "term": "selic", "contribution": 0.1},
                    ]
                }
            ),
        )

        matched = asyncio.run(feed.contributions(env, {"selic": 1.0, "copom": 0.5}))

        assert matched == {1: {"selic": 0.4, "copom": 0.2}, 2: {"selic": 0.1}}

    def test_an_empty_profile_never_reaches_the_database(self, monkeypatch):
        """The cold start path costs one query less than the personalized one."""
        env = patched(monkeypatch, FakeEnv())

        assert asyncio.run(feed.contributions(env, {})) == {}
        assert env.calls == []

    def test_the_query_stays_under_the_bound_parameter_ceiling(self, monkeypatch):
        """Each profile term is bound twice in the CASE and once in the IN.

        D1 refuses a statement over 100, and a reader with many likes carries far
        more terms than that, so the cap is what keeps the feed answering.
        """
        env = patched(monkeypatch, FakeEnv())
        wide = {f"termo{i}": 1.0 / (i + 1) for i in range(200)}

        asyncio.run(feed.contributions(env, wide))

        _, params = env.calls[0]
        assert len(params) == feed.PROFILE_TERMS * 3
        assert len(params) <= 100
