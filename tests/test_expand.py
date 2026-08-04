"""Tests for the two counterweights to the absorbing state.

A subject never touched has a cosine near zero, so it never rises, so it is never
shown, so it can never be liked, so it never enters the profile. That is
arithmetic rather than an opinion, and these are the two things that break it:
reaching along edges the corpus drew, and reserving slots outright.
"""

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


class TestInterleave:
    def card(self, cluster_id, similarity, sources=3):
        return {"cluster_id": cluster_id, "similarity": similarity, "sources": sources}

    def everything(self):
        ranked = [self.card(i, 0.2) for i in range(40)]
        surprises = [self.card(100 + i, 0.0) for i in range(10)]
        return ranked + surprises

    def test_no_slider_means_no_reserved_slots(self):
        page = feed.interleave(self.everything(), 0.0, 0)

        assert all(not card.get("discovery") for card in page)
        assert len(page) == feed.PAGE

    def test_a_share_of_the_page_goes_to_what_the_profile_ignored(self):
        page = feed.interleave(self.everything(), 0.25, 0)
        reserved = [card for card in page if card["discovery"]]

        assert len(reserved) == feed.PAGE // 4
        assert all(card["similarity"] == 0.0 for card in reserved)

    def test_a_story_the_profile_has_any_opinion_about_is_not_a_discovery(self):
        """The badge tells the reader the profile's strongest terms say nothing
        about this story, so any contribution at all disqualifies it.

        A ceiling here instead of zero was comparing two rulers. `similarity` is
        completed from a dot product over the twenty terms the query binds, not
        against the whole profile, while the ceiling of 0.011 had been read off
        the true cosine. Measured over twenty profiles on the live window, 26% of
        the cards that took a reserved slot had a true cosine above that ceiling.
        """
        faint = [self.card(200 + i, 0.0001) for i in range(10)]
        page = feed.interleave([self.card(i, 0.2) for i in range(40)] + faint, 0.25, 0)

        assert not any(card["discovery"] for card in page)

    def test_reserved_slots_are_spread_through_the_page(self):
        """Collected at the end they would be a section the reader learns to
        skip, which fails the same way as not reserving them.
        """
        page = feed.interleave(self.everything(), 0.25, 0)
        positions = [i for i, card in enumerate(page) if card["discovery"]]

        assert max(positions) - min(positions) > feed.PAGE // 2

    def test_an_obscure_story_does_not_take_a_slot(self):
        """A slot spent on something no other portal ran teaches the reader to
        ignore the badge.
        """
        pool = [self.card(i, 0.2) for i in range(40)]
        pool += [self.card(100 + i, 0.0, sources=1) for i in range(10)]

        page = feed.interleave(pool, 0.25, 0)

        assert all(not card["discovery"] for card in page)

    def test_a_slot_with_nothing_to_put_in_it_returns_to_the_ranking(self):
        """A promise of discovery is not a reason to show worse news."""
        pool = [self.card(i, 0.2) for i in range(40)]

        page = feed.interleave(pool, 0.25, 0)

        assert len(page) == feed.PAGE

    def test_the_second_page_does_not_repeat_the_first(self):
        everything = self.everything()
        first = feed.interleave(everything, 0.25, 0)
        second = feed.interleave(everything, 0.25, feed.PAGE)

        assert not {c["cluster_id"] for c in first} & {c["cluster_id"] for c in second}
