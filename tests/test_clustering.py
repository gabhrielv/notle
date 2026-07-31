"""Tests for cluster assignment.

Slice 1 gives every article its own cluster. The point of the seam is that
slice 2 replaces this one function and nothing above it changes: the feed, the
materialized candidates, the API and the card already speak cluster.
"""

from ingest.clustering import assign_cluster
from ingest.feeds import ArticleDraft

DRAFT = ArticleDraft(
    source_id=1,
    title="Copom mantem a Selic em 10,5% ao ano",
    summary="O Comite de Politica Monetaria decidiu",
    url="https://exemplo.com/copom",
    published_at="2026-07-31T12:00:00Z",
)

VECTOR = {"copom": 0.4, "selic": 0.4, "juros": 0.2}


def test_slice_one_never_attaches_to_an_existing_cluster():
    """None means: open a new cluster for this article."""
    recent = [
        (11, {"copom": 0.4, "selic": 0.4, "juros": 0.2}),
        (12, {"eleição": 0.5, "urna": 0.5}),
    ]

    assert assign_cluster(DRAFT, VECTOR, recent) is None


def test_an_identical_neighbour_still_does_not_capture_the_article():
    """Pins the slice 1 behaviour explicitly.

    A cosine of exactly 1.0 against a recent cluster is the strongest possible
    case for attaching, and slice 1 still declines. When this test starts
    failing, slice 2 has landed.
    """
    recent = [(11, dict(VECTOR))]

    assert assign_cluster(DRAFT, VECTOR, recent) is None


def test_no_recent_clusters_is_handled():
    assert assign_cluster(DRAFT, VECTOR, []) is None
