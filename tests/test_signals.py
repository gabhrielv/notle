"""Tests for the implicit half of the funnel.

Every value here is a guess about intent read off a browser event, so what is
pinned is not the numbers but the shape: which guesses are allowed to matter,
which are refused, and the bound that keeps all of them under the smallest thing
a reader actually said.
"""

import math

from api import signals


class TestCeiling:
    """The architecture's rule, as an inequality rather than an intention."""

    def test_everything_implicit_together_stays_under_one_like(self):
        """A reader who dwelt on a card, clicked it and came back having read it
        has done the most the funnel can measure without saying anything. It
        still has to be worth less than one press of Interessa.
        """
        assert signals.most_one_cluster_can_gather() < signals.CEILING

    def test_an_impression_contributes_nothing_to_that_total(self):
        """Not a placeholder. If display fed the profile, the ranking would show
        what the reader already likes, the display would confirm it, the profile
        would tighten, and the system would be measuring its own output.
        """
        assert signals.IMPRESSION == 0.0

    def test_the_strongest_implicit_signal_is_under_half_a_like(self):
        """Clicking through is the most a reader does without speaking, and the
        architecture is explicit that it still only adjusts.
        """
        assert signals.CLICK < signals.CEILING / 2


class TestAccept:
    """What a browser is allowed to say, and what it is not."""

    def test_the_value_is_computed_here_rather_than_accepted(self):
        """The reason this layer exists.

        A client reporting what a signal was worth would be a client writing
        straight into someone's taste profile. What it may say is what happened
        and for how long.
        """
        rows = signals.accept(
            [{"type": "click", "cluster_id": 7, "value": 99.0, "duration_ms": 1000}]
        )

        assert rows == [("click", 7, signals.CLICK, 0)]

    def test_a_type_nobody_defined_is_refused(self):
        assert signals.accept([{"type": "like", "cluster_id": 7}]) == []
        assert signals.accept([{"type": "purchase", "cluster_id": 7}]) == []

    def test_an_impression_survives_at_zero(self):
        """Stored because the ranking counts the rows to stop offering a story a
        fourth time, and worth nothing because it measures the ranking's own
        choice rather than the reader's.
        """
        rows = signals.accept([{"type": "impression", "cluster_id": 7}])

        assert rows == [("impression", 7, 0.0, 0)]

    def test_anything_else_worth_nothing_is_dropped(self):
        """A return too late to read and a dwell of no time say nothing, and
        storing them would cost a scan on every profile rebuild forever.
        """
        assert signals.accept([{"type": "return", "cluster_id": 7, "duration_ms": 900_000}]) == []
        assert signals.accept([{"type": "dwell", "cluster_id": 7, "duration_ms": 0}]) == []

    def test_malformed_events_do_not_take_the_batch_down(self):
        """One bad row in a batch of thirty must not lose the other twenty nine."""
        rows = signals.accept(
            [
                "nao e um evento",
                {"type": "click"},
                {"type": "click", "cluster_id": "7"},
                {"type": "click", "cluster_id": True},
                {"cluster_id": 7},
                {"type": "click", "cluster_id": 9},
            ]
        )

        assert rows == [("click", 9, signals.CLICK, 0)]

    def test_a_duration_that_is_not_a_number_is_read_as_none(self):
        assert signals.accept([{"type": "dwell", "cluster_id": 7, "duration_ms": "muito"}]) == []
        assert signals.accept([{"type": "return", "cluster_id": 7, "duration_ms": None}]) == []

    def test_a_batch_beyond_the_ceiling_is_trimmed_rather_than_refused(self):
        """A bug in the client should cost the reader nothing."""
        events = [{"type": "impression", "cluster_id": i} for i in range(500)]

        assert len(signals.accept(events)) == signals.MAX_BATCH

    def test_nothing_reported(self):
        assert signals.accept([]) == []
        assert signals.accept(None) == []


class TestDwell:
    def test_longer_on_a_card_is_worth_more(self):
        assert signals.dwell_value(8, 200) > signals.dwell_value(2, 200)

    def test_it_measures_reading_rather_than_how_much_a_portal_writes(self):
        """The bias this normalization exists to stop.

        One portal writes longer headlines than another, so without this the
        reader spends more seconds on its cards, the weight climbs, and the
        ranking learns a source preference nobody has. The same reading speed on
        both has to be worth the same.
        """
        long_card = signals.dwell_value(seconds=12, text_length=440)
        short_card = signals.dwell_value(seconds=4, text_length=147)

        assert math.isclose(long_card, short_card, rel_tol=0.05)

    def test_it_saturates_rather_than_rewarding_an_abandoned_tab(self):
        assert signals.dwell_value(600, 200) == signals.DWELL_MAX

    def test_a_card_reporting_no_text_is_still_scored(self):
        """It was on screen and it was read. The client failing to measure its
        own headline is not the reader's doing.
        """
        assert signals.dwell_value(5, 0) > 0

    def test_no_time_on_a_card_is_no_signal(self):
        assert signals.dwell_value(0, 200) == 0.0


class TestReturn:
    def test_coming_straight_back_cancels_the_click_and_costs_more(self):
        """A return in five seconds has one plausible reading, and it is
        rejection. The click has to be undone, not merely left standing.
        """
        value = signals.return_value(5)

        assert value < 0
        assert abs(value) > signals.CLICK

    def test_the_middle_says_nothing_either_way(self):
        assert signals.return_value(30) == 0.0

    def test_coming_back_after_reading_is_positive(self):
        assert signals.return_value(90) > 0

    def test_it_saturates_so_a_forgotten_tab_is_worth_a_real_read(self):
        assert signals.return_value(280) == signals.RETURN_MAX

    def test_a_return_too_late_to_mean_anything_is_discarded(self):
        """Four minutes has ten explanations and reading is not the likeliest: a
        message answered, a phone in a pocket, lunch. Only the half of this
        signal that carries information is used, and the rest is absence of
        evidence rather than evidence of absence.
        """
        assert signals.return_value(400) == 0.0
        assert signals.return_value(3600) == 0.0

    def test_a_negative_duration_is_not_a_signal(self):
        """Clocks move backwards, and a tab restored from the back forward cache
        can report one.
        """
        assert signals.return_value(-10) == 0.0

    def test_the_curve_never_inverts(self):
        """Reading longer must never be worth less, or the ranking would prefer
        the reader who skimmed.
        """
        span = [61, 90, 150, 240, 299]
        values = [signals.return_value(s) for s in span]

        assert values == sorted(values)
