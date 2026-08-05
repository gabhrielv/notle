"""Tests for the ranking arithmetic.

These are the constants the architecture says must stop being intuition, so what
is pinned here is the shape of the formula rather than the values: which term
dominates when, and what happens at the edges the demo will actually hit.
"""

import math
from datetime import UTC, datetime

import pytest

from ranking.score import (
    BETA,
    DISCOVERY_CAP,
    HALF_LIFE_HOURS,
    IMPRESSION_LIMIT,
    NEGATIVE_FLOOR,
    W_DESCOBERTA,
    W_GOSTO,
    W_RECENCIA,
    age_in_hours,
    decay,
    discovery_lift,
    rejection,
    repetition,
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
        """0.044 was the ninetieth percentile of measured profile to candidate
        cosine on the live window. A candidate that good has to be worth being
        half a day old, or the ranking is a clock with extra steps.
        """
        assert score(0.044, age_hours=HALF_LIFE_HOURS) > score(0.0, age_hours=0)

    def test_a_story_old_enough_ranks_below_a_worse_but_fresher_one(self):
        """The decay multiplies the whole thing, floor included.

        A perfect match from three days ago has to lose to an indifferent one
        from this morning, or the feed stops being news.
        """
        assert score(1.0, age_hours=72) < score(0.0, age_hours=1)


class TestRepetition:
    """How long the feed keeps offering a story the reader has not answered."""

    def test_a_story_never_shown_keeps_all_of_its_score(self):
        assert repetition(0) == 1.0

    def test_one_pass_across_the_screen_does_not_kill_it(self):
        """The sentence that reconciles the two halves of the rule. A good story
        does not vanish for having been on screen; it takes three.
        """
        assert 0 < repetition(1) < 1.0
        assert repetition(1) > repetition(2) > 0

    def test_one_showing_moves_a_story_by_a_page_and_not_by_the_corpus(self):
        """Measured off the live feed, where scores are packed very tightly:
        position 1 scores 0.0386, position 25 scores 0.0358, position 193
        scores 0.0275. So what matters is not how large the penalty looks but
        how far it moves a card.

        The first shape tried here took a third off at the first impression,
        which pushed a story from the top of the feed to beyond position 192.
        The growing penalty and the third showing then never happened, because
        the first one decided everything.
        """
        top, page_two, deep = 0.0386, 0.0358, 0.0275

        assert top * repetition(1) > page_two * 0.97
        assert top * repetition(2) > deep

    def test_the_third_showing_is_the_last(self):
        assert repetition(IMPRESSION_LIMIT) == 0.0
        assert repetition(IMPRESSION_LIMIT + 5) == 0.0

    def test_it_damps_rather_than_subtracts(self):
        """Subtracting enough to matter drives the score under zero, and under
        zero the decay inverts: multiplying a negative by a smaller number makes
        it larger, so the staler of two over shown stories would climb above the
        fresher one. Damping keeps every score on one side of zero.
        """
        fresh = score(0.05, age_hours=0) * repetition(2)
        stale = score(0.05, age_hours=36) * repetition(2)

        assert fresh > stale > 0

    def test_being_shown_never_makes_a_story_rank_higher(self):
        assert repetition(1) < repetition(0)


class TestRejection:
    """Which negative cosines the ranking is willing to act on."""

    def test_shared_vocabulary_is_not_a_shared_subject(self):
        """0.08 was a story about technical courses matching one about a football
        coach, on the word `tecnico`. A bag of lemmas cannot tell those apart, so
        below the floor the evidence is refused rather than discounted.
        """
        assert rejection(0.08) == 0.0

    def test_the_subject_itself_gets_through(self):
        """0.139, 0.122 and 0.119 were the three genuine football stories the
        measurement found. All of them have to survive the cut.
        """
        assert rejection(0.139) == 0.139
        assert rejection(NEGATIVE_FLOOR) == NEGATIVE_FLOOR

    def test_nothing_in_common_costs_nothing(self):
        assert rejection(0.0) == 0.0


class TestNegativeProfile:
    """What a hidden subject costs a story that resembles it."""

    def test_a_reader_who_has_hidden_nothing_pays_nothing(self):
        """The common path. Almost nobody hides anything, and that path has to be
        the same expression with one term absent rather than a separate branch.
        """
        assert score(0.05, age_hours=3) == score(0.05, age_hours=3, penalty=0.0)

    def test_the_worst_resemblance_costs_about_one_half_life(self):
        """The sentence BETA is supposed to mean, checked.

        0.381 was the strongest cosine observed between a profile and a candidate
        on the live window. What it costs has to land near the floor, which is
        itself defined as the affinity worth one half life. Much more than that
        and the card is banished instead of demoted, which is the failure the
        first value chosen here actually produced.
        """
        worst = BETA * 0.381

        assert 0.5 * W_RECENCIA < worst < 2.0 * W_RECENCIA

    def test_resembling_the_hidden_side_sinks_below_an_unknown_story(self):
        """Hiding has to reach past the one card it was aimed at.

        A story about nothing the reader has an opinion on scores the floor. One
        that looks like what they rejected must come out under it, or the hide
        did nothing except remove a single cluster.
        """
        assert score(0.0, age_hours=0, penalty=0.12) < score(0.0, age_hours=0)

    def test_taste_outweighs_rejection_when_the_reader_has_expressed_both(self):
        """The half of this the first BETA got wrong, and the state the two
        vectors exist for.

        A card the reader's taste matches strongly and their rejection also
        touches has to stay well above an unremarkable fresh story, or the card
        can never be seen and the reason it carries is written for nobody. With
        both cosines at the strongest observed on the live window, it does.
        """
        both_sides = score(0.381, age_hours=0, penalty=0.381)
        fresh_and_plain = score(0.0, age_hours=0)

        assert both_sides > fresh_and_plain

    def test_the_worst_case_costs_almost_the_whole_floor_and_no_more(self):
        """Where the corrected BETA lands, stated as a bound in both directions.

        A reader who has hidden something and liked nothing has an empty positive
        side, so every candidate scores the recency floor and the strongest
        resemblance gives back almost all of it: 0.0019 of 0.04. The card sinks
        under everything inside the 48 hour window, which is the correct reading
        of the only preference this reader has expressed.

        What it must not do is go negative. Below zero the ordering among
        rejected stories stops meaning anything, because the decay can no longer
        separate them, and that was the failure of the first BETA.
        """
        worst = score(0.0, age_hours=0, penalty=0.381)

        assert 0 < worst < 0.1 * W_RECENCIA
        assert worst < score(0.0, age_hours=48)

    def test_two_rejected_stories_are_still_ordered_by_freshness(self):
        """The reason the penalty has to stay smaller than the floor.

        Once scores go negative the decay inverts: multiplying a negative by a
        smaller number makes it larger, so the older of two unwanted stories
        would rank higher. Keeping the worst case inside the floor is what stops
        that, and it is the same inversion the two separate vectors exist to
        avoid in the first place.
        """
        assert score(0.0, age_hours=1, penalty=0.35) > score(0.0, age_hours=30, penalty=0.35)

    def test_the_hidden_subject_still_loses_to_a_plain_fresh_story(self):
        """The gesture has to be worth making.

        A story that looks like what the reader rejected must come out under an
        untouched one of the same moment, however strong its own freshness.
        """
        assert score(0.0, age_hours=0, penalty=0.12) < score(0.0, age_hours=0)
        assert score(0.0, age_hours=0, penalty=0.381) < score(0.0, age_hours=0)

    def test_the_penalty_does_not_decay_away(self):
        """The penalty sits outside the decay on purpose.

        Inside it, a rejected subject would be forgiven for getting old, and two
        days later the feed would drift back to exactly what the reader asked it
        to drop. Here the older of two equally unwanted stories still ranks
        lower, because only the part worth keeping shrinks with age.
        """
        fresh = score(0.10, age_hours=0, penalty=0.12)
        stale = score(0.10, age_hours=48, penalty=0.12)

        assert stale < fresh

    def test_a_strong_match_survives_a_resemblance_to_something_hidden(self):
        """Both vectors can have an opinion about one card, and the stronger one
        should win rather than the negative one deciding by itself.
        """
        assert score(0.15, age_hours=0, penalty=0.12) > score(0.0, age_hours=0)


class TestAgeInHours:
    def test_reads_the_format_the_corpus_stores(self):
        assert age_in_hours("2026-07-31T06:00:00Z", NOW) == 6.0

    def test_a_story_published_this_second_has_no_age(self):
        assert age_in_hours("2026-07-31T12:00:00Z", NOW) == 0.0

    def test_crossing_a_day_boundary(self):
        assert age_in_hours("2026-07-30T12:00:00Z", NOW) == 24.0


class TestDiscoveryLift:
    """What coverage is worth to a story the profile has no opinion about."""

    def test_a_reader_who_asked_for_none_gets_none(self):
        assert discovery_lift(0.0, 4, 0.0) == 0.0

    def test_a_story_one_portal_ran_is_not_a_find(self):
        assert discovery_lift(0.0, 1, 0.5) == 0.0

    def test_a_story_the_profile_has_any_opinion_about_is_not_a_find(self):
        """The same line the badge draws. Where the ranking has something to say,
        it says it, and coverage does not get to speak instead.
        """
        assert discovery_lift(0.0001, 4, 0.5) == 0.0

    def test_at_the_top_of_the_slider_two_extra_portals_are_worth_one_half_life(self):
        """The stated reading of the constant, and the whole reason it is 0.04.
        `W_RECENCIA` is the affinity worth one half life, so this says a third
        portal buys exactly as much as being one half life fresher.

        One portal for one half life was the first reading, and the simulator
        refused it: at the top of the slider every card on the page arrived by
        coverage and precision fell to zero.
        """
        assert discovery_lift(0.0, 3, 0.5) == pytest.approx(W_RECENCIA)

    def test_the_constant_is_what_that_reading_requires(self):
        assert W_DESCOBERTA * 0.5 * 2 == pytest.approx(W_RECENCIA)

    def test_the_cap_is_where_the_control_ends(self):
        """The handler clamps to this and the curve measures travel against it.
        The same number in two files under no name is how they come apart.
        """
        assert DISCOVERY_CAP == 0.5

    def test_the_curve_is_concave_so_the_first_notch_is_not_dead(self):
        """The property the whole change exists for. Linear in the slider, the
        lower third delivered nothing: measured over 18 profiles, a tenth of the
        travel moved 0.2 cards of 24 while the last tenth moved 1.4. Concave, the
        first tenth is worth more than the last, which is what makes moving the
        control do something wherever it is.
        """
        primeiro = discovery_lift(0.0, 2, 0.1) - discovery_lift(0.0, 2, 0.0)
        ultimo = discovery_lift(0.0, 2, 0.5) - discovery_lift(0.0, 2, 0.4)

        assert primeiro > ultimo

    def test_the_far_end_is_where_it_always_was(self):
        """The curve changes the path and not the destination, so the reading
        the constant was chosen for still holds at the cap.
        """
        assert discovery_lift(0.0, 3, DISCOVERY_CAP) == pytest.approx(W_RECENCIA)

    def test_it_still_rises_with_the_slider(self):
        assert discovery_lift(0.0, 2, 0.4) > discovery_lift(0.0, 2, 0.1)

    def test_more_portals_lift_more(self):
        assert discovery_lift(0.0, 4, 0.5) > discovery_lift(0.0, 2, 0.5)

    def test_a_bolder_reader_is_lifted_more(self):
        assert discovery_lift(0.0, 3, 0.5) > discovery_lift(0.0, 3, 0.1)


class TestScoreWithDiscovery:
    def test_coverage_can_lift_a_story_the_profile_ignores(self):
        """Both are strangers to this reader and the same age, so the only thing
        separating them is how many newsrooms thought it was the day's story.
        """
        covered = score(0.0, 1.0, discovery_value=discovery_lift(0.0, 3, 0.5))
        alone = score(0.0, 1.0, discovery_value=discovery_lift(0.0, 1, 0.5))

        assert covered > alone

    def test_the_lift_ages_with_the_story(self):
        """Inside the decay and not beside it. Outside, a well covered story
        would be perpetually resurrected, and news dies in 48 hours.
        """
        lift = discovery_lift(0.0, 4, 0.5)

        assert score(0.0, 1.0, discovery_value=lift) > score(
            0.0, 48.0, discovery_value=lift
        )

    def test_a_reader_at_zero_ranks_exactly_as_before(self):
        assert score(0.02, 3.0, discovery_value=0.0) == score(0.02, 3.0)
