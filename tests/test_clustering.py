"""Tests for cluster assignment.

The numbers here are hand built rather than lemmatized from text, so a failure
points at the matching and not at the language model. The one test that does run
real headlines through the pipeline lives in test_pipeline.py.
"""

import math

from ingest.clustering import SIMILARITY_THRESHOLD, assign_cluster, cosine, idf, weigh


class TestIdf:
    def test_a_term_in_every_document_separates_nothing(self):
        assert idf(doc_count=100, total_docs=100) == 0.0

    def test_a_rare_term_outweighs_a_common_one(self):
        assert idf(doc_count=2, total_docs=1000) > idf(doc_count=500, total_docs=1000)

    def test_a_term_the_corpus_has_not_counted_yet_does_not_divide_by_zero(self):
        """Every term of the first article to use it arrives with doc_count zero.

        The counts are read before the run writes anything, so this is the
        normal case for new vocabulary, not an edge.
        """
        assert idf(doc_count=0, total_docs=300) == math.log(300)

    def test_an_empty_corpus_yields_no_weight_rather_than_an_error(self):
        """IDF is corpus knowledge and an empty corpus has none.

        A run against a fresh database groups nothing and the next hourly run
        clusters normally. Raising here would take the whole ingestion down on
        the very first pass instead.
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


class TestAssignCluster:
    def test_no_candidates_opens_a_new_cluster(self):
        assert assign_cluster({"selic": 1.0}, []) is None

    def test_a_neighbour_below_the_threshold_is_left_alone(self):
        """Two stories can share their common vocabulary without being one story.

        This is the pair that fixed the threshold, both real: "Unidade Popular
        oficializa candidaturas ao governo e Senado no Para" against "PCdoB
        oficializa apoio a candidatura de Lula". They are different events that
        happen to share the words Brazilian election coverage always uses.

        It is weighting that separates them, and the two numbers below are the
        argument for doing it: on raw frequency the pair reads as near identical,
        and only rarity reveals that everything they share is boilerplate.
        """
        counts = {
            "oficializar": 90,
            "candidatura": 70,
            "unidade popular": 1,
            "pará": 20,
            "pcdob": 2,
            "lula": 120,
        }
        raw_vector = {"oficializar": 0.3, "candidatura": 0.3, "unidade popular": 0.2, "pará": 0.2}
        raw_candidate = {"oficializar": 0.3, "candidatura": 0.3, "pcdob": 0.2, "lula": 0.2}

        assert cosine(raw_vector, raw_candidate) > 0.5

        vector = weigh(raw_vector, counts, total_docs=311)
        candidate = weigh(raw_candidate, counts, total_docs=311)

        assert cosine(vector, candidate) < SIMILARITY_THRESHOLD
        assert assign_cluster(vector, [(11, candidate)]) is None

    def test_the_same_story_from_another_portal_attaches(self):
        vector = {"copom": 0.4, "selic": 0.4, "juros": 0.2}
        candidate = {"copom": 0.35, "selic": 0.45, "banco central": 0.2}

        assert assign_cluster(vector, [(11, candidate)]) == 11

    def test_the_strongest_match_wins_not_the_first_one_over_the_line(self):
        """The window comes back in whatever order SQLite chose.

        Taking the first candidate above the threshold would make the grouping
        depend on that order, which nothing promises to keep stable.
        """
        vector = {"selic": 0.5, "copom": 0.5}
        weak = {"selic": 0.5, "inflação": 0.5}
        strong = {"selic": 0.45, "copom": 0.55}

        assert assign_cluster(vector, [(11, weak), (12, strong)]) == 12
        assert assign_cluster(vector, [(12, strong), (11, weak)]) == 12

    def test_a_score_exactly_on_the_threshold_attaches(self):
        """Pins which side of the line the comparison sits on."""
        vector = {"a": 1.0}
        candidate = {"a": SIMILARITY_THRESHOLD, "b": math.sqrt(1 - SIMILARITY_THRESHOLD**2)}

        assert math.isclose(cosine(vector, candidate), SIMILARITY_THRESHOLD)
        assert assign_cluster(vector, [(11, candidate)]) == 11

    def test_an_article_that_shares_nothing_opens_its_own_cluster(self):
        assert assign_cluster({"futebol": 1.0}, [(11, {"selic": 1.0})]) is None
