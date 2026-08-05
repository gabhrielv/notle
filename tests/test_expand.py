"""Tests for the two counterweights to the absorbing state.

A subject never touched has a cosine near zero, so it never rises, so it is never
shown, so it can never be liked, so it never enters the profile. That is
arithmetic rather than an opinion, and these are the two things that break it:
reaching along edges the corpus drew, and letting coverage across portals lift
what the profile has no opinion about.
"""

from datetime import UTC, datetime

from api import expand, feed
from ingest import cooccurrence


class TestDice:
    def test_terms_that_always_appear_together_score_one(self):
        assert cooccurrence.dice(together=10, docs_a=10, docs_b=10) == 1.0

    def test_a_pair_that_never_meets_scores_nothing(self):
        assert cooccurrence.dice(together=0, docs_a=10, docs_b=10) == 0.0

    def test_a_common_term_does_not_become_everybody_s_neighbour(self):
        """The failure raw counts produce. `governo` shares more articles with
        `selic` than `cambio` does purely by being common, so counting would put
        the corpus's commonest words next to everything and expansion would drag
        a profile to the centre instead of sideways.
        """
        common = cooccurrence.dice(together=40, docs_a=45, docs_b=800)
        specific = cooccurrence.dice(together=30, docs_a=45, docs_b=50)

        assert specific > common

    def test_a_term_nobody_used_is_not_a_division(self):
        assert cooccurrence.dice(together=0, docs_a=0, docs_b=0) == 0.0


class TestEligibleTerms:
    COUNTS = {"selic": 40, "cambio": 30, "raro": 2}

    def test_a_term_seen_twice_has_no_evidence(self):
        """Whatever shares those two articles scores perfectly against it."""
        assert "raro" not in cooccurrence.eligible_terms(self.COUNTS)

    def test_one_portal_alone_is_furniture_rather_than_a_subject(self):
        """Without this the strongest neighbour of `google` came back as
        `favorite o g1`, at 0.51, because G1 pastes that line into its technology
        articles and Dice cannot tell a newsroom habit from a habit of the
        language.
        """
        spread = {"selic": 4, "cambio": 1}
        eligible = cooccurrence.eligible_terms(self.COUNTS, spread)

        assert "selic" in eligible
        assert "cambio" not in eligible

    def test_what_the_normalizer_would_throw_away_never_gets_neighbours(self):
        """Applied here as well as there because the two act at different times:
        `article_terms` holds what the normalizer decided when the article
        arrived, so a word added to the discard list only changes what is stored
        from then on.
        """
        counts = {"leia": 90, "selic": 40}

        assert "leia" not in cooccurrence.eligible_terms(counts)


class TestExpanded:
    EDGES = {
        "selic": [("cambio", 0.4), ("inflacao", 0.3)],
        "copom": [("selic", 0.6)],
    }

    def test_it_reaches_subjects_the_reader_never_touched(self):
        reached = expand.expanded({"selic": 1.0}, self.EDGES)

        assert set(reached) == {"cambio", "inflacao"}

    def test_a_neighbour_never_outweighs_what_the_reader_chose(self):
        """The expanded profile is an offer, not a claim. The reader said nothing
        about these subjects; the corpus merely observed they sit next door.
        """
        reached = expand.expanded({"selic": 1.0}, self.EDGES)

        assert max(reached.values()) < 1.0

    def test_a_stronger_edge_reaches_further(self):
        reached = expand.expanded({"selic": 1.0}, self.EDGES)

        assert reached["cambio"] > reached["inflacao"]

    def test_it_does_not_repeat_what_the_profile_already_holds(self):
        """Keeping them would make this a louder copy of the long profile, and
        every point of extra agreement is spent against what it exists for.
        """
        reached = expand.expanded({"copom": 1.0, "selic": 1.0}, self.EDGES)

        assert "selic" not in reached

    def test_a_reader_who_has_said_nothing_reaches_nothing(self):
        assert expand.expanded({}, self.EDGES) == {}

class TestDiscoveryOnThePage:
    """The badge follows the news now, not the slider."""

    def rows(self, sources):
        """Candidates that differ only in how many portals ran them."""
        return [
            {
                "cluster_id": i,
                "base_score": 0.0,
                "norm": 1.0,
                "published_at": "2026-07-31T11:00:00Z",
                "top_terms": "[]",
                "sources": n,
            }
            for i, n in enumerate(sources)
        ]

    def page(self, sources, ratio, profile_norm=2.0):
        """`profile_norm` above zero is a reader who already has a taste. Zero is
        somebody who does not yet, and the badge does not speak to them.
        """
        return feed.scored(
            self.rows(sources),
            {},
            profile_norm,
            set(),
            datetime(2026, 7, 31, 12, tzinfo=UTC),
            discovery_ratio=ratio,
        )

    def test_a_reader_who_asked_for_none_sees_none(self):
        page = self.page([1, 2, 3, 4], 0.0)

        assert not any(card["discovery"] for card in page)

    def test_only_what_several_portals_ran_is_marked(self):
        page = self.page([1, 1, 3, 4], 0.5)
        marked = {card["cluster_id"] for card in page if card["discovery"]}

        assert marked == {2, 3}

    def test_the_count_follows_the_window_rather_than_the_slider(self):
        """The whole point. The same slider over a day with no coverage marks
        nothing, where the old quota would have filled half the page regardless.
        """
        assert sum(c["discovery"] for c in self.page([1, 1, 1, 1], 0.5)) == 0
        assert sum(c["discovery"] for c in self.page([2, 2, 2, 2], 0.5)) == 4

    def test_coverage_lifts_a_stranger_above_a_stranger(self):
        page = self.page([1, 4], 0.5)

        assert page[0]["cluster_id"] == 1

    def test_interleave_now_only_cuts_the_page(self):
        everything = [{"cluster_id": i} for i in range(40)]

        assert feed.interleave(everything, 0) == everything[: feed.PAGE]
        assert feed.interleave(everything, feed.PAGE)[0]["cluster_id"] == feed.PAGE

    def test_a_reader_with_no_taste_is_not_told_what_is_outside_it(self):
        """The badge claims a contrast: nothing among your strongest terms
        appears here. With no terms the sentence is empty, and printing it on
        most of the page is the same failure the quota had, a label that
        distinguishes nothing. Measured live at the default it was 16 cards of
        24.
        """
        page = self.page([2, 3, 4], 0.5, profile_norm=0.0)

        assert not any(card["discovery"] for card in page)

    def test_coverage_still_orders_a_feed_it_cannot_name(self):
        """A better cold start than the clock, using the signal the onboarding
        already trusts. The lift acts; only the naming waits for a profile.
        """
        page = self.page([1, 4], 0.5, profile_norm=0.0)

        assert page[0]["cluster_id"] == 1

    def test_a_reader_with_taste_is_told(self):
        page = self.page([1, 3], 0.5)
        marked = {card["cluster_id"] for card in page if card["discovery"]}

        assert marked == {1}
