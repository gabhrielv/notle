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


class TestNegativeVectors:
    def test_reads_only_what_the_reader_hid(self, monkeypatch):
        env = patched(monkeypatch, FakeEnv())

        asyncio.run(profile.negative_vectors(env, "u1"))

        _, params = env.calls[0]
        assert "hide" in params
        assert "like" not in params
        assert "share" not in params

    def test_builds_a_vector_the_same_way_the_positive_side_does(self, monkeypatch):
        """Both directions have to be described in one vocabulary.

        The two cosines are compared against each other in the formula, so a
        hide read through a different join than a like would put the two sides
        on different rulers and make BETA meaningless.
        """
        env = patched(
            monkeypatch,
            FakeEnv(
                {
                    "FROM interactions i": [
                        {"cluster_id": 7, "type": "hide", "term": "futebol", "tf": 0.7},
                        {"cluster_id": 7, "type": "hide", "term": "escalação", "tf": 0.3},
                    ]
                }
            ),
        )

        vectors = asyncio.run(profile.negative_vectors(env, "u1"))

        assert vectors == [({"futebol": 0.7, "escalação": 0.3}, 1.0)]


class TestLoad:
    def test_a_visitor_with_no_row_yet_has_neither_vector(self, monkeypatch):
        env = patched(monkeypatch, FakeEnv())

        assert asyncio.run(profile.load(env, "u1")) == ({}, {})

    def test_reads_both_columns_of_one_row(self, monkeypatch):
        env = patched(
            monkeypatch,
            FakeEnv(
                {
                    "FROM user_profile": [
                        {
                            "term_vector": '{"selic": 1.0}',
                            "neg_term_vector": '{"futebol": 1.0}',
                        }
                    ]
                }
            ),
        )

        assert asyncio.run(profile.load(env, "u1")) == ({"selic": 1.0}, {"futebol": 1.0})
        assert len(env.calls) == 1

    def test_a_column_that_is_not_readable_json_does_not_take_the_feed_down(
        self, monkeypatch
    ):
        """One unreadable column must not cost the other one.

        The stored vectors are a cache of the log, so the honest recovery is an
        empty profile rather than an error: the next interaction rebuilds both.
        """
        env = patched(
            monkeypatch,
            FakeEnv(
                {
                    "FROM user_profile": [
                        {"term_vector": "{nao e json", "neg_term_vector": '{"futebol": 1.0}'}
                    ]
                }
            ),
        )

        assert asyncio.run(profile.load(env, "u1")) == ({}, {"futebol": 1.0})


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

    def test_a_reader_who_hid_nothing_gets_the_same_order_as_before(self):
        """The negative side is absent for almost every visitor, and absent has
        to mean untouched rather than handled.
        """
        without = feed.rank(self.rows(), {1: {"selic": 0.5}}, 1.0, set(), NOW)
        with_empty = feed.rank(self.rows(), {1: {"selic": 0.5}}, 1.0, set(), NOW, {}, 0.0)

        assert [c["cluster_id"] for c in without] == [c["cluster_id"] for c in with_empty]
        assert all(card["against"] == [] for card in without)

    def test_looking_like_something_hidden_costs_a_card_its_place(self):
        """Cluster 2 is the fresher of the two and would lead on the floor alone.

        It resembles what the reader hid, so it goes under the one that does
        not. This is the half of slice 3 that a reader can actually feel: the
        hide reaches past the single card it was aimed at.
        """
        ranked = feed.rank(
            self.rows(), {}, 0.0, set(), NOW, {2: {"futebol": 0.5}}, 1.0
        )

        assert [card["cluster_id"] for card in ranked] == [1, 2]

    def test_a_faint_overlap_neither_costs_nor_is_named(self):
        """The floor, seen from the feed.

        A candidate sharing a little vocabulary with something hidden keeps its
        place and says nothing about it. Naming a reason the ranking declined to
        act on would put a sentence on the card that the number underneath does
        not support.
        """
        ranked = feed.rank(
            self.rows(), {}, 0.0, set(), NOW, {2: {"experiência": 0.04}}, 1.0
        )
        card = next(c for c in ranked if c["cluster_id"] == 2)

        assert card["penalty"] == 0
        assert card["against"] == []

    def test_the_card_names_what_pushed_it_down(self):
        ranked = feed.rank(
            self.rows(),
            {1: {"selic": 0.4}},
            1.0,
            set(),
            NOW,
            {1: {"futebol": 0.2, "escalação": 0.9}},
            1.0,
        )
        card = next(c for c in ranked if c["cluster_id"] == 1)

        assert card["because"] == ["selic"]
        assert card["against"] == ["escalação", "futebol"]

    def test_both_directions_can_appear_on_one_card(self):
        """The tug of war the separate vectors exist to represent.

        A card can be lifted by one subject and pulled down by another at the
        same time, and the screen is supposed to say both rather than net them
        into a single number the reader cannot take apart.
        """
        ranked = feed.rank(
            self.rows(), {1: {"selic": 0.4}}, 1.0, set(), NOW, {1: {"futebol": 0.2}}, 1.0
        )
        card = next(c for c in ranked if c["cluster_id"] == 1)

        assert card["because"] and card["against"]
        assert card["similarity"] > 0
        assert card["penalty"] > 0


class TestHeldBack:
    """The account the feed gives of what a hide moved.

    A penalty is larger than the whole spread of scores inside a page, so
    anything it touches lands well outside it. Without this list the reader sees
    a cluster disappear and never learns that the same gesture pushed others
    down, which is the half of slice 3 the card could not deliver.
    """

    def card(self, cluster_id, penalty=0.0):
        return {"cluster_id": cluster_id, "penalty": penalty}

    def test_a_reader_who_hid_nothing_is_told_nothing(self):
        everything = [self.card(i) for i in range(feed.PAGE + 20)]

        assert feed.held_back(everything) == []

    def test_only_what_the_penalty_pushed_past_the_page_is_counted(self):
        """A story that is merely far down is not a story that was moved. Only a
        penalty makes it the reader's own doing, and only that is worth naming.
        """
        everything = [self.card(i) for i in range(feed.PAGE)]
        everything += [self.card(900, 0.13), self.card(901), self.card(902, 0.11)]

        assert [c["cluster_id"] for c in feed.held_back(everything)] == [900, 902]

    def test_a_penalised_card_that_still_made_the_page_is_left_alone(self):
        """It is on screen carrying its own reason, so repeating it below would
        be the same explanation twice.
        """
        everything = [self.card(1, 0.14)] + [self.card(i) for i in range(2, feed.PAGE + 5)]

        assert feed.held_back(everything) == []

    def test_the_worst_hit_come_first(self):
        everything = [self.card(i) for i in range(feed.PAGE)]
        everything += [self.card(900, 0.11), self.card(901, 0.15), self.card(902, 0.13)]

        assert [c["cluster_id"] for c in feed.held_back(everything)] == [901, 902, 900]

    def test_it_is_an_account_and_not_a_second_feed(self):
        everything = [self.card(i) for i in range(feed.PAGE)]
        everything += [self.card(900 + i, 0.13) for i in range(40)]

        assert len(feed.held_back(everything)) == feed.HELD_BACK


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

        matched = asyncio.run(
            feed.contributions(env, {"selic": 1.0, "copom": 0.5}, {"selic": 2.0, "copom": 3.0})
        )

        assert matched == {1: {"selic": 0.4, "copom": 0.2}, 2: {"selic": 0.1}}

    def test_the_bound_weight_carries_both_sides_of_the_idf(self, monkeypatch):
        """The regression this whole module turns on.

        `article_terms` holds raw TF, so what the database multiplies it by has
        to contain the candidate's IDF as well as the profile's, or the numerator
        is weighed once while `feed_candidates.norm` is weighed twice.

        Binding only the profile weight is not an error that cancels: measured
        against the live window it ran from 3.1x to 7.2x depending on which terms
        matched, compressing every candidate into a band 0.017 to 0.021 wide and
        letting a story about technical courses outrank one about a football
        coach.
        """
        env = patched(monkeypatch, FakeEnv())

        asyncio.run(feed.contributions(env, {"selic": 0.5}, {"selic": 4.0}))

        _, params = env.calls[0]
        assert params[:2] == ["selic", 2.0]

    def test_an_empty_profile_never_reaches_the_database(self, monkeypatch):
        """The cold start path costs one query less than the personalized one."""
        env = patched(monkeypatch, FakeEnv())

        assert asyncio.run(feed.contributions(env, {}, {})) == {}
        assert env.calls == []

    def test_the_query_stays_under_the_bound_parameter_ceiling(self, monkeypatch):
        """Each profile term is bound twice in the CASE and once in the IN.

        D1 refuses a statement over 100, and a reader with many likes carries far
        more terms than that, so the cap is what keeps the feed answering.
        """
        env = patched(monkeypatch, FakeEnv())
        wide = {f"termo{i}": 1.0 / (i + 1) for i in range(200)}

        asyncio.run(feed.contributions(env, wide, dict.fromkeys(wide, 2.0)))

        _, params = env.calls[0]
        assert len(params) == feed.PROFILE_TERMS * 3
        assert len(params) <= 100
