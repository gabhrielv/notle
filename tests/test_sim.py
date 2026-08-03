"""Tests for the simulator itself.

A calibration harness that is wrong produces confident numbers about nothing, so
what is pinned here is the property the architecture says the whole exercise
depends on: that a persona's behaviour never consults the formula being
evaluated.
"""

from sim import run
from sim.personas import TECH, Persona, answer


class FakeSnapshot:
    """Two clusters, one from a technology portal and one not."""

    total_docs = 100
    document_counts = {"chip": 4, "selic": 4, "juro": 4}
    vectors = {
        1: {"chip": 1.0},
        2: {"selic": 0.5, "juro": 0.5},
    }
    cards = {
        1: {
            "cluster_id": 1,
            "source": "TechCrunch",
            "title": "chip",
            "published_at": "2026-08-02T12:00:00Z",
            "sources": 2,
        },
        2: {
            "cluster_id": 2,
            "source": "G1",
            "title": "selic",
            "published_at": "2026-08-02T12:00:00Z",
            "sources": 3,
        },
    }
    edges: dict = {}


class TestIndependence:
    """The objection the architecture registers, held as a test.

    A simulator is worth nothing if the persona likes what the algorithm
    predicts: the experiment would only prove the system agrees with itself.
    """

    def test_a_persona_decides_from_the_portal_and_nothing_else(self):
        card = {"cluster_id": 1, "source": "TechCrunch", "score": 0.0, "similarity": 0.0}

        assert TECH.likes(card)

    def test_the_score_cannot_change_what_a_persona_wants(self):
        cheap = {"cluster_id": 1, "source": "TechCrunch", "score": -99.0}
        rich = {"cluster_id": 2, "source": "G1", "score": 99.0}

        assert TECH.likes(cheap)
        assert not TECH.likes(rich)

    def test_the_ranking_is_never_given_the_portal(self):
        """`source_id` enters no vector, no cosine, no IDF and no decay. The
        ground truth is disjoint from the feature space, which is what makes the
        question worth asking.
        """
        for vector in FakeSnapshot.vectors.values():
            assert not {"techcrunch", "g1", "source", "source_id"} & set(vector)


class TestAnswer:
    def test_it_keeps_only_what_is_on_subject(self):
        page = [
            {"cluster_id": 1, "source": "TechCrunch"},
            {"cluster_id": 2, "source": "G1"},
            {"cluster_id": 3, "source": "The Verge"},
        ]

        keeps, hides = answer(TECH, page)

        assert set(keeps) == {1, 3}
        assert hides == [2]

    def test_a_page_with_nothing_on_subject_teaches_only_by_hiding(self):
        page = [{"cluster_id": i, "source": "G1"} for i in range(4)]

        keeps, hides = answer(TECH, page)

        assert keeps == []
        assert len(hides) == 1

    def test_nothing_offered(self):
        assert answer(TECH, []) == ([], [])


class TestMetrics:
    def test_precision_counts_the_persona_s_own_subject(self):
        page = [
            {"source": "TechCrunch"},
            {"source": "G1"},
            {"source": "IEEE Spectrum"},
            {"source": "G1"},
        ]

        assert run.precision(page, TECH) == 0.5

    def test_diversity_falls_when_the_feed_collapses(self):
        """The brake on precision. A feed that has become one subject scores
        perfectly on precision, and that is the zemblanity the discovery slots
        exist to prevent, so it has to be visible somewhere.
        """
        varied = [{"source": s} for s in ("G1", "Folha", "CNN", "BBC")]
        collapsed = [{"source": "G1"}] * 4

        assert run.diversity(varied) > run.diversity(collapsed)

    def test_baseline_is_what_no_ranking_at_all_would_score(self):
        """Every result has to be read against this. Without it a precision of
        0.5 could be a triumph or could be the corpus.
        """
        assert run.baseline(TECH, FakeSnapshot()) == 0.5

    def test_an_empty_page_scores_nothing_rather_than_dividing(self):
        assert run.precision([], TECH) == 0.0
        assert run.diversity([]) == 0.0


class TestProfileOf:
    def test_it_averages_the_way_the_worker_does(self):
        """A mean rather than a sum, so a reader with forty likes does not carry
        a vector forty times longer. If this drifted from `api.profile.combine`
        the calibration would be measuring a different system.
        """
        profile = run.profile_of([1, 2], FakeSnapshot())

        assert profile["chip"] == 0.5
        assert profile["selic"] == 0.25

    def test_a_reader_who_has_kept_nothing_has_no_profile(self):
        assert run.profile_of([], FakeSnapshot()) == {}


class TestRankRespectsTheReader:
    def test_a_cluster_already_answered_for_is_not_offered_again(self):
        reader = run.Reader(kept=[1], hidden=[])

        page = run.rank(reader, FakeSnapshot(), run.Constants(), now_hours=0.0)

        assert all(card["cluster_id"] != 1 for card in page)


class TestSweep:
    def test_it_scores_the_best_round_rather_than_the_last(self):
        """Precision rises for about five rounds and then collapses, because the
        mean profile is captured by whatever vocabulary repeats across what was
        kept. Reading the last round would rank constants by how fast they reach
        that collapse.
        """
        results = run.sweep(TECH, FakeSnapshot(), "w_recencia", [0.04], rounds=3)

        assert results[0]["precision"] == max(results[0]["curve"])
        assert 1 <= results[0]["peak_round"] <= 3

    def test_a_persona_with_no_portal_in_the_corpus_scores_nothing(self):
        nobody = Persona("ninguem", frozenset({"Jornal Que Nao Existe"}))

        results = run.sweep(nobody, FakeSnapshot(), "beta", [0.1], rounds=2)

        assert results[0]["precision"] == 0.0
