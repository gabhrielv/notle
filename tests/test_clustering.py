"""Tests for cluster assignment.

The vector arithmetic underneath is covered in test_vectors.py, and the one test
that runs real headlines through the pipeline lives in test_pipeline.py.
"""

import math

from ingest.clustering import SIMILARITY_THRESHOLD, assign_cluster
from ranking.vectors import cosine, weigh


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
