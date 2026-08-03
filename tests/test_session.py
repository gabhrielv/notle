"""Tests for the reader's last few minutes.

What is pinned here is the pair of locks the architecture puts on the session
profile: that scattered reading earns it nothing, and that focused reading can
never earn it more than the cap. Between those two the number is allowed to be
whatever the arithmetic says.
"""

import math

from api import session

# Three clusters about one event, and three about nothing in common. The shapes
# stand in for what the measurement found on the live corpus: a real run scored
# 0.287 between its clusters, a scattered session 0.068.
RUN = [
    {"lula": 0.5, "convenção": 0.3, "pt": 0.2},
    {"lula": 0.4, "convenção": 0.4, "palanque": 0.2},
    {"lula": 0.5, "pt": 0.3, "discurso": 0.2},
]
SCATTERED = [
    {"futebol": 0.6, "treinador": 0.4},
    {"festival": 0.7, "ingresso": 0.3},
    {"caneta": 0.5, "obesidade": 0.5},
]


class TestFocus:
    def test_a_run_on_one_subject_scores_high(self):
        assert session.focus(RUN) > session.FOCUS_FULL / 2

    def test_unrelated_reading_scores_near_nothing(self):
        assert session.focus(SCATTERED) == 0.0

    def test_a_mixed_session_lands_between_them(self):
        """The case entropy got backwards, ranking it below both extremes."""
        mixed = [RUN[0], RUN[1], SCATTERED[0]]

        assert session.focus(SCATTERED) < session.focus(mixed) < session.focus(RUN)

    def test_one_story_is_not_a_run(self):
        """No pair to compare, and calling a single story a focused session would
        hand the cap to anyone who read one thing.
        """
        assert session.focus([RUN[0]]) == 0.0
        assert session.focus([]) == 0.0


class TestWeight:
    def test_scattered_reading_earns_no_say(self):
        """It zeroes itself, which is what makes the weight adaptive rather than
        a constant someone has to remember to turn off.
        """
        assert session.weight(SCATTERED) == 0.0

    def test_a_run_on_one_subject_reaches_most_of_the_cap(self):
        """The cap is the point rather than a safety margin. Without it, three
        taps on sport convert the rest of the session into sport, because the
        reinforcement produces the engagement that produces the reinforcement.
        """
        assert session.weight(RUN) > session.MAX_WEIGHT * 0.8

    def test_it_never_exceeds_the_cap(self):
        identical = [{"selic": 1.0}, {"selic": 1.0}, {"selic": 1.0}]

        assert session.weight(identical) == session.MAX_WEIGHT
        assert session.weight(RUN) <= session.MAX_WEIGHT

    def test_the_session_can_never_outvote_the_long_profile(self):
        """The architecture's line, as an inequality: the last ten minutes
        adjust what the reader has spent weeks saying, they do not replace it.
        """
        assert session.MAX_WEIGHT < 1.0


class TestDecayed:
    def test_signals_close_together_stack_almost_whole(self):
        """Three interactions on one subject inside ninety seconds are three
        nearly complete contributions.
        """
        burst = [({"selic": 1.0}, 1.0, minutes) for minutes in (0.0, 0.5, 1.5)]

        assert session.decayed(burst)["selic"] > 2.7

    def test_the_same_signals_spread_out_arrive_at_almost_nothing(self):
        """How fast someone is reading falls out of the arithmetic, with no code
        anywhere computing a rate.
        """
        spread = [({"selic": 1.0}, 1.0, minutes) for minutes in (0.0, 25.0, 55.0)]

        assert session.decayed(spread)["selic"] < 1.2

    def test_one_half_life_halves_a_contribution(self):
        recent = session.decayed([({"selic": 1.0}, 1.0, 0.0)])
        older = session.decayed([({"selic": 1.0}, 1.0, session.HALF_LIFE_MINUTES)])

        assert math.isclose(older["selic"], recent["selic"] / 2)

    def test_a_stronger_signal_still_says_more_inside_the_session(self):
        """A like in the last minute has to outweigh a dwell in the last minute,
        or the session would read the weakest evidence and ignore the loudest.
        """
        like = session.decayed([({"selic": 1.0}, 1.0, 0.0)])
        dwell = session.decayed([({"selic": 1.0}, 0.15, 0.0)])

        assert like["selic"] > dwell["selic"]

    def test_a_signal_that_cancelled_out_contributes_nothing(self):
        """A click followed by an immediate return sums to a negative, and the
        honest reading is that the reader looked and left.
        """
        assert session.decayed([({"selic": 1.0}, -0.5, 0.0)]) == {}

    def test_nothing_in_this_session(self):
        assert session.decayed([]) == {}


class TestLeading:
    def test_it_names_the_subject_of_a_real_run(self):
        folded = session.decayed([(terms, 1.0, 0.0) for terms in RUN])

        assert session.leading(folded, RUN) == "lula"

    def test_it_says_nothing_when_the_ranking_was_given_nothing(self):
        """Telling a reader they are on a run about something, while the formula
        weighted that run at almost zero, would describe a force that is not
        acting on anything they can see.
        """
        folded = session.decayed([(terms, 1.0, 0.0) for terms in SCATTERED])

        assert session.leading(folded, SCATTERED) is None

    def test_no_session_names_nothing(self):
        assert session.leading({}, []) is None
