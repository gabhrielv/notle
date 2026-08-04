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

import pytest

from api import browse, feed, onboarding, profile, session, users

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)
NOW_ISO = "2026-07-31T12:00:00Z"


def row(cluster_id, weight, term, tf):
    """One `signal_vectors` row, with the timestamp its decay needs."""
    return {
        "cluster_id": cluster_id,
        "weight": weight,
        "last_at": NOW_ISO,
        "term": term,
        "tf": tf,
    }


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
    monkeypatch.setattr(browse, "query", fake_query)
    monkeypatch.setattr(onboarding, "query", fake_query)
    return env


class TestOnboardingPicks:
    """What the cold start accepts as an answer."""

    OFFERED = {11, 12, 13, 14}

    def test_keeps_the_choices_that_were_on_the_screen(self):
        assert onboarding._valid([13, 11], self.OFFERED) == [13, 11]

    def test_an_id_that_was_never_offered_is_dropped(self):
        """`interactions.cluster_id` carries no foreign key, so an id that never
        existed would be stored happily and then poison the profile rebuild with
        a join that matches nothing.
        """
        assert onboarding._valid([99, 11], self.OFFERED) == [11]

    def test_the_same_choice_twice_counts_once(self):
        """Otherwise a doubled pick weighs double in the mean, and the reader
        never said it twice.
        """
        assert onboarding._valid([11, 11, 12], self.OFFERED) == [11, 12]

    def test_more_than_asked_for_is_trimmed(self):
        assert len(onboarding._valid([11, 12, 13, 14], self.OFFERED)) == onboarding.PICKS

    def test_junk_is_not_an_answer(self):
        assert onboarding._valid("11", self.OFFERED) == []
        assert onboarding._valid(None, self.OFFERED) == []
        assert onboarding._valid([{"cluster_id": 11}, "11", 1.5], self.OFFERED) == []

    def test_choosing_nothing_is_allowed(self):
        """Skipping is an answer the system has to accept. The way past a screen
        that will not take no is the close button.
        """
        assert onboarding._valid([], self.OFFERED) == []


class TestOnboardingAnswer:
    def test_skipping_still_marks_the_reader_as_done(self, monkeypatch):
        """Without the mark a visitor who skipped meets the same form on every
        visit, which is the failure the column exists to prevent.
        """
        env = patched(monkeypatch, FakeEnv())
        writes = []

        async def fake_execute(env, sql, params=None):
            writes.append(sql)

        monkeypatch.setattr(onboarding, "execute", fake_execute)

        chosen = asyncio.run(onboarding.answer(env, "u1", []))

        assert chosen == []
        assert any("UPDATE users SET onboarded_at" in sql for sql in writes)
        assert not any("INSERT INTO interactions" in sql for sql in writes)

    def test_choices_are_written_as_seed_rather_than_like(self, monkeypatch):
        """Choosing among twelve headlines in a form is not the gesture of
        keeping a story while reading, and once the two are written as one type
        the distinction never comes back.
        """
        env = patched(
            monkeypatch,
            FakeEnv({"FROM onboarding_picks": [{"cluster_id": 11}, {"cluster_id": 12}]}),
        )
        writes = []

        async def fake_execute(env, sql, params=None):
            writes.append((sql, list(params or [])))

        monkeypatch.setattr(onboarding, "execute", fake_execute)

        chosen = asyncio.run(onboarding.answer(env, "u1", [12, 11]))

        assert chosen == [12, 11]
        inserted = next(sql for sql, _ in writes if "INSERT INTO interactions" in sql)
        assert "'seed'" in inserted
        assert "'like'" not in inserted


class TestMatchExpression:
    """What a person types, turned into something FTS5 will accept."""

    def test_every_word_has_to_appear(self):
        """Space is AND in FTS5. Under OR a search for two words would come back
        full of stories matching only the commoner one, which reads as broken.
        """
        assert browse.match_expression("selic copom") == '"selic" "copom"'

    def test_syntax_is_stripped_rather_than_escaped(self):
        """A search box takes text, not an expression. `Selic?` should find what
        `Selic` finds, and a stray quote should not become an error the reader
        has to work out.
        """
        assert browse.match_expression('selic? "copom"') == '"selic" "copom"'
        assert browse.match_expression("NEAR(a b)") == '"NEAR" "a" "b"'

    def test_punctuation_on_its_own_leaves_nothing_to_search_for(self):
        assert browse.match_expression("?? **") == ""

    def test_nothing_typed(self):
        assert browse.match_expression("   ") == ""


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
                        row(1, 1.0, "selic", 0.6),
                        row(1, 1.0, "copom", 0.4),
                        row(2, 1.5, "futebol", 1.0),
                    ]
                }
            ),
        )

        vectors = asyncio.run(profile.positive_vectors(env, "u1", NOW))

        assert sorted(vectors, key=lambda pair: pair[1]) == [
            ({"selic": 0.6, "copom": 0.4}, 1.0),
            ({"futebol": 1.0}, 1.5),
        ]

    def test_hide_is_not_a_positive_signal(self, monkeypatch):
        env = patched(monkeypatch, FakeEnv())

        asyncio.run(profile.positive_vectors(env, "u1"))

        _, params = env.calls[0]
        assert "hide" not in params


class TestFaded:
    """The long profile's time constant, which the code did not have until now.

    The architecture's table of the four vectors gives this one months. Without
    it a like from a year ago weighed exactly as much as one from a minute ago,
    so a profile accumulated forever and nothing a reader stopped caring about
    ever left.
    """

    def test_a_signal_from_this_moment_arrives_whole(self):
        assert profile.faded(1.0, NOW_ISO, NOW.timestamp()) == 1.0

    def test_one_half_life_halves_it(self):
        later = NOW.timestamp() + profile.LONG_HALF_LIFE_DAYS * 86400

        assert profile.faded(1.0, NOW_ISO, later) == pytest.approx(0.5)

    def test_last_week_is_essentially_untouched(self):
        week = NOW.timestamp() + 7 * 86400

        assert profile.faded(1.0, NOW_ISO, week) > 0.9

    def test_a_year_ago_is_gone_without_being_deleted(self):
        """It faded rather than expired, which is what the constant says should
        happen. The reader is never told a preference was dropped.
        """
        year = NOW.timestamp() + 365 * 86400
        remains = profile.faded(1.0, NOW_ISO, year)

        assert 0 < remains < 0.02

    def test_the_session_and_the_long_profile_read_the_same_rows_differently(self):
        """Ten minutes against sixty days, off one log. That is the whole reason
        interactions are stored as events rather than folded into a number.
        """
        assert profile.LONG_HALF_LIFE_DAYS * 24 * 60 > session.HALF_LIFE_MINUTES * 1000

    def test_a_clock_running_backwards_does_not_amplify_a_signal(self):
        earlier = NOW.timestamp() - 86400

        assert profile.faded(1.0, NOW_ISO, earlier) == 1.0

    def test_an_unreadable_date_costs_the_age_and_not_the_signal(self):
        """Losing one interaction's timestamp should not lose the interaction."""
        assert profile.faded(1.0, "nao e uma data", NOW.timestamp()) == 1.0
        assert profile.faded(1.0, None, NOW.timestamp()) == 1.0

    def test_a_signal_worth_nothing_stays_worth_nothing(self):
        assert profile.faded(0.0, NOW_ISO, NOW.timestamp()) == 0.0


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
                        row(7, 1.0, "futebol", 0.7),
                        row(7, 1.0, "escalação", 0.3),
                    ]
                }
            ),
        )

        vectors = asyncio.run(profile.negative_vectors(env, "u1", NOW))

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


class TestWeighted:
    """The document floor that keeps a single article from posing as a taste."""

    def counts(self, **by_term):
        return {"FROM terms": [{"term": t, "doc_count": n} for t, n in by_term.items()]}

    def test_a_term_the_corpus_saw_once_does_not_describe_a_taste(self, monkeypatch):
        """Podcast show notes are the case. `episode` and `decel` reach the
        vector of anybody who likes one podcast article, and being rare is
        exactly what makes IDF hand them the largest weight it has.
        """
        env = patched(monkeypatch, FakeEnv(self.counts(decel=1, selic=200)))

        weighted, factors = asyncio.run(
            profile.weighted(env, {"decel": 0.5, "selic": 0.5}, 5505)
        )

        assert "decel" not in weighted
        assert "decel" not in factors
        assert "selic" in weighted

    def test_a_term_at_the_floor_is_kept(self):
        assert profile.PROFILE_MIN_DOCS == 5, "a medicao abaixo foi feita contra 5"

    def test_a_term_the_corpus_never_counted_is_dropped(self, monkeypatch):
        """Missing from `terms` used to read as `doc_count` zero, which the IDF
        floor then turned into the largest weight in the vector. Absence of
        corpus knowledge is not evidence of rarity.
        """
        env = patched(monkeypatch, FakeEnv(self.counts(selic=200)))

        weighted, _ = asyncio.run(profile.weighted(env, {"fantasma": 1.0}, 5505))

        assert weighted == {}

    def test_the_returned_factors_cover_exactly_what_survived(self, monkeypatch):
        """The caller binds the factor per term to complete the dot product, so
        a factor for a term that is no longer in the vector would weigh a
        candidate against something the profile stopped claiming.
        """
        env = patched(monkeypatch, FakeEnv(self.counts(decel=1, selic=200, juro=40)))

        weighted, factors = asyncio.run(
            profile.weighted(env, {"decel": 0.3, "selic": 0.4, "juro": 0.3}, 5505)
        )

        assert set(weighted) == set(factors)

    def test_an_empty_vector_asks_the_database_nothing(self, monkeypatch):
        env = patched(monkeypatch, FakeEnv())

        assert asyncio.run(profile.weighted(env, {}, 5505)) == ({}, {})
        assert env.calls == []


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

    def test_scrolling_past_the_first_page_continues_the_same_order(self):
        """Offset paging is safe here for a reason particular to this corpus: the
        ranking only moves when the ingestion runs, once an hour, so page two is
        page one's list further down rather than a fresh ranking.
        """
        many = [
            {
                "cluster_id": i,
                "base_score": 1.0,
                "norm": 1.0,
                "published_at": "2026-07-31T12:00:00Z",
                "top_terms": "[]",
            }
            for i in range(feed.PAGE * 2 + 5)
        ]

        first = feed.rank(many, {}, 0.0, set(), NOW)
        second = feed.rank(many, {}, 0.0, set(), NOW, offset=feed.PAGE)
        whole = feed.scored(many, {}, 0.0, set(), NOW)

        assert len(second) == feed.PAGE
        assert not {c["cluster_id"] for c in first} & {c["cluster_id"] for c in second}
        assert [c["cluster_id"] for c in first + second] == [
            c["cluster_id"] for c in whole[: feed.PAGE * 2]
        ]

    def test_the_last_page_comes_back_short_so_the_scroll_can_stop(self):
        many = [
            {
                "cluster_id": i,
                "base_score": 1.0,
                "norm": 1.0,
                "published_at": "2026-07-31T12:00:00Z",
                "top_terms": "[]",
            }
            for i in range(feed.PAGE + 3)
        ]

        assert len(feed.rank(many, {}, 0.0, set(), NOW, offset=feed.PAGE)) == 3

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


class TestShorten:
    """How much of a summary reaches the card.

    What the feeds call a summary is not one thing. Measured across the corpus,
    The Register averages 84 characters and Engadget 113, while G1, Canaltech,
    IEEE and Agencia Brasil all sit at 595, which is the ingestion's 600
    character cap doing its work on what is really the article's body.
    """

    def test_a_real_summary_passes_through_untouched(self):
        """Ten of the twenty sources write short enough that nothing happens to
        them, and a card should not carry an ellipsis it did not earn.
        """
        short = "Copom mantem a Selic em 10,5% ao ano."

        assert feed.shorten(short) == short

    def test_an_article_body_is_cut_to_the_same_shape(self):
        body = "palavra " * 200

        assert len(feed.shorten(body)) <= feed.SUMMARY_CHARS + 1

    def test_it_cuts_on_a_word_boundary(self):
        """Mid word is worse than short: the reader sees a fragment and the
        ellipsis lands inside a name.
        """
        text = "Ministro " * 40

        assert feed.shorten(text).rstrip("…").endswith("Ministro")

    def test_a_feed_that_publishes_no_summary_gets_no_ellipsis(self):
        """Tecmundo shipped forty items with nothing in the field. A headline
        with no text under it is a normal card, not a broken one.
        """
        assert feed.shorten("") == ""
        assert feed.shorten(None) == ""

    def test_the_clamp_happens_before_the_client_sees_it(self):
        """The client reports how much text was on screen so a dwell can be
        normalized by it. Hiding the overflow with CSS instead would inflate
        that number with words nobody read.
        """
        assert feed.SUMMARY_CHARS < 600


class TestBrowse:
    """The two lists that ignore taste."""

    def test_the_timeline_leaves_out_what_the_reader_hid(self, monkeypatch):
        env = patched(monkeypatch, FakeEnv())

        asyncio.run(browse.latest(env, offset=0, hidden={7, 9}))

        sql, params = env.calls[0]
        assert "NOT IN" in sql
        assert 7 in params and 9 in params

    def test_a_reader_who_hid_nothing_gets_no_exclusion_clause(self, monkeypatch):
        """An empty set must not become `NOT IN ()`, which is a syntax error."""
        env = patched(monkeypatch, FakeEnv())

        asyncio.run(browse.latest(env, offset=0, hidden=set()))

        sql, _ = env.calls[0]
        assert "NOT IN" not in sql

    def test_the_exclusion_stays_under_the_bound_parameter_ceiling(self, monkeypatch):
        """D1 refuses a statement over 100 parameters, and the page needs three.

        Past the cap the tail of the hides stops being filtered, which shows the
        reader a story they hid. Refusing the request instead would show them
        nothing at all.
        """
        env = patched(monkeypatch, FakeEnv())

        asyncio.run(browse.latest(env, offset=0, hidden=set(range(500))))

        _, params = env.calls[0]
        assert len(params) == browse.MAX_EXCLUSIONS + 2
        assert len(params) <= 100

    def test_a_cluster_with_no_headline_yet_is_not_offered(self, monkeypatch):
        """The ingestion opens a cluster before it knows the article id that
        will represent it, so a row can exist with nothing to show.
        """
        env = patched(monkeypatch, FakeEnv())

        asyncio.run(browse.latest(env, offset=0, hidden=set()))

        sql, _ = env.calls[0]
        assert "representative_article_id IS NOT NULL" in sql

    def test_searching_for_nothing_never_reaches_the_database(self, monkeypatch):
        env = patched(monkeypatch, FakeEnv())

        assert asyncio.run(browse.search(env, "  ", offset=0)) == []
        assert env.calls == []

    def test_search_groups_by_cluster(self, monkeypatch):
        """Several portals cover one story, so ungrouped results repeat the same
        headline, which is the repetition clustering exists to remove arriving
        through a different door.
        """
        env = patched(monkeypatch, FakeEnv())

        asyncio.run(browse.search(env, "selic", offset=0))

        sql, params = env.calls[0]
        assert "GROUP BY cluster_id" in sql
        assert "AS MATERIALIZED" in sql
        assert params[0] == '"selic"'

    def test_search_does_not_read_the_profile(self, monkeypatch):
        """A question with a right answer. Withholding a story the reader asked
        for by name, because they once hid something like it, would make the box
        untrustworthy.
        """
        env = patched(monkeypatch, FakeEnv())

        asyncio.run(browse.search(env, "selic", offset=0))

        assert all("interactions" not in sql for sql, _ in env.calls)
        assert all("user_profile" not in sql for sql, _ in env.calls)


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
