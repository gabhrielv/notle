"""Tests for the ranking arithmetic.

These are the constants the architecture says must stop being intuition, so what
is pinned here is the shape of the formula rather than the values: which term
dominates when, and what happens at the edges the demo will actually hit.
"""

import math
from datetime import UTC, datetime

from ranking.score import (
    HALF_LIFE_HOURS,
    W_GOSTO,
    W_RECENCIA,
    age_in_hours,
    decay,
    score,
    similarity,
)

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


class TestDecay:
    def test_a_story_from_now_keeps_all_of_its_weight(self):
        assert decay(0) == 1.0

    def test_one_half_life_halves_it(self):
        assert math.isclose(decay(HALF_LIFE_HOURS), 0.5)

    def test_two_days_old_is_nearly_spent(self):
        """News dies in 48 hours, and the curve has to agree with that."""
        assert 0.05 < decay(48) < 0.07

    def test_a_timestamp_from_the_future_is_treated_as_fresh(self):
        """A portal publishing on a clock that runs ahead is a real thing.

        Without the clamp its stories earn a multiplier above one and take the
        top of the feed on nothing but a bad timestamp.
        """
        assert decay(-6) == 1.0


class TestSimilarity:
    def test_completes_the_cosine_the_database_started(self):
        assert similarity(dot=6.0, profile_norm=3.0, cluster_norm=4.0) == 0.5

    def test_an_empty_profile_has_no_affinity_rather_than_an_error(self):
        """Every visitor is anonymous, so this is the common case, not an edge.

        Dividing by a zero length would take down the first request of every
        person who ever opens the demo.
        """
        assert similarity(dot=0.0, profile_norm=0.0, cluster_norm=4.0) == 0.0


class TestScore:
    def test_with_an_empty_profile_the_feed_orders_by_freshness(self):
        """The cold start needs no branch: it is the formula with one term at zero.

        This is the screen most visitors will only ever see, so it has to be
        ordered by something rather than tied.
        """
        fresh = score(similarity_value=0.0, age_hours=1)
        older = score(similarity_value=0.0, age_hours=25)

        assert fresh > older > 0

    def test_affinity_can_beat_freshness(self):
        """Otherwise the ranking is a clock and the profile is decoration."""
        matched_and_old = score(similarity_value=0.8, age_hours=6)
        unmatched_and_new = score(similarity_value=0.0, age_hours=0)

        assert matched_and_old > unmatched_and_new

    def test_freshness_still_separates_two_equally_good_matches(self):
        assert score(0.5, age_hours=1) > score(0.5, age_hours=10)

    def test_the_floor_is_what_an_unrelated_story_of_this_moment_scores(self):
        assert math.isclose(score(similarity_value=0.0, age_hours=0), W_RECENCIA)

    def test_the_floor_is_the_affinity_worth_exactly_one_half_life(self):
        """The one reading of W_RECENCIA that makes it measurable.

        Because the decay multiplies the floor too, a story with cosine equal to
        W_RECENCIA ties an unrelated story one half life fresher. Above it, taste
        buys age; below it, the feed is ordered by the clock. Getting this
        backwards is how the first value chosen here made the profile decorative.
        """
        matched_but_older = score(W_RECENCIA / W_GOSTO, age_hours=HALF_LIFE_HOURS)
        unmatched_but_fresh = score(0.0, age_hours=0)

        assert math.isclose(matched_but_older, unmatched_but_fresh)

    def test_a_top_decile_match_outranks_a_fresh_story_about_nothing(self):
        """0.028 was the ninetieth percentile of measured profile to candidate
        cosine on the live window. A candidate that good has to be worth being
        half a day old, or the ranking is a clock with extra steps.
        """
        assert score(0.028, age_hours=HALF_LIFE_HOURS) > score(0.0, age_hours=0)

    def test_a_story_old_enough_ranks_below_a_worse_but_fresher_one(self):
        """The decay multiplies the whole thing, floor included.

        A perfect match from three days ago has to lose to an indifferent one
        from this morning, or the feed stops being news.
        """
        assert score(1.0, age_hours=72) < score(0.0, age_hours=1)


class TestAgeInHours:
    def test_reads_the_format_the_corpus_stores(self):
        assert age_in_hours("2026-07-31T06:00:00Z", NOW) == 6.0

    def test_a_story_published_this_second_has_no_age(self):
        assert age_in_hours("2026-07-31T12:00:00Z", NOW) == 0.0

    def test_crossing_a_day_boundary(self):
        assert age_in_hours("2026-07-30T12:00:00Z", NOW) == 24.0
