"""Tests for the vector arithmetic both runtimes share.

The numbers are hand built rather than lemmatized from text, so a failure points
at the arithmetic and not at the language model.
"""

import math

from ranking.vectors import cosine, idf, norm, strongest, weigh


class TestIdf:
    def test_a_term_in_every_document_separates_nothing(self):
        assert idf(doc_count=100, total_docs=100) == 0.0

    def test_a_rare_term_outweighs_a_common_one(self):
        assert idf(doc_count=2, total_docs=1000) > idf(doc_count=500, total_docs=1000)

    def test_a_term_the_corpus_has_not_counted_yet_does_not_divide_by_zero(self):
        """Every term of the first article to use it arrives with doc_count zero.

        Counts are read before a run writes anything, so this is the normal case
        for new vocabulary, not an edge.
        """
        assert idf(doc_count=0, total_docs=300) == math.log(300)

    def test_an_empty_corpus_yields_no_weight_rather_than_an_error(self):
        """IDF is corpus knowledge and an empty corpus has none.

        Raising here would take the whole ingestion down on its first pass.
        """
        assert idf(doc_count=0, total_docs=0) == 0.0


class TestWeigh:
    def test_rarity_reorders_the_vector(self):
        """`governo` appears everywhere, `copom` does not.

        Raw frequency puts them level. The point of weighting is that what
        identifies a story is the term the rest of the corpus does not use.
        """
        weighted = weigh(
            {"governo": 0.5, "copom": 0.5},
            document_counts={"governo": 900, "copom": 4},
            total_docs=1000,
        )

        assert weighted["copom"] > weighted["governo"]


class TestNorm:
    def test_length_of_a_known_triangle(self):
        assert norm({"a": 3.0, "b": 4.0}) == 5.0

    def test_an_empty_vector_has_no_length(self):
        assert norm({}) == 0.0


class TestCosine:
    def test_identical_vectors(self):
        v = {"selic": 0.6, "copom": 0.4}

        assert math.isclose(cosine(v, dict(v)), 1.0)

    def test_vectors_sharing_no_term(self):
        assert cosine({"selic": 1.0}, {"futebol": 1.0}) == 0.0

    def test_direction_matters_and_length_does_not(self):
        """A long summary and a short one about the same event must match.

        Term frequencies already sum to one, but IDF weighting scales them back
        apart, so the magnitude has to divide out here.
        """
        assert math.isclose(cosine({"selic": 1.0, "juros": 1.0}, {"selic": 5.0, "juros": 5.0}), 1.0)

    def test_an_empty_vector_matches_nothing(self):
        assert cosine({}, {"selic": 1.0}) == 0.0


class TestStrongest:
    def test_returns_the_heaviest_terms_first(self):
        vector = {"selic": 0.2, "copom": 0.9, "juro": 0.5}

        assert strongest(vector, 2) == ["copom", "juro"]

    def test_asking_for_more_than_there_is_returns_what_there_is(self):
        assert strongest({"selic": 1.0}, 10) == ["selic"]

    def test_ties_break_on_the_term_so_the_choice_is_reproducible(self):
        """The feed sends these to the database.

        Two terms of equal weight resolving differently between requests would
        change which candidates are even looked at, and the same profile would
        produce a different feed for no reason the screen could explain.
        """
        vector = {"juro": 0.5, "copom": 0.5, "selic": 0.5}

        assert strongest(vector, 2) == ["copom", "juro"]

    def test_nothing_to_rank(self):
        assert strongest({}, 5) == []
