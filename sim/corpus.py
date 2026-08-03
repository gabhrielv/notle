"""One snapshot of the corpus, held in memory so a simulation costs nothing.

Pulled once from D1 and reused across every run of the grid. A calibration sweep
is fifty simulations of a hundred rounds each, and reading the window from the
database inside that loop would make the sweep a network benchmark rather than a
ranking one.

Cached on disk for the same reason: the corpus does not change while a sweep is
being interpreted, and re-reading it between two attempts at the same question
only introduces a difference nobody asked for.
"""

import json
import os
from dataclasses import dataclass, field

from ingest.store import D1Client

CACHE = os.environ.get("NOTLE_SIM_CACHE", ".sim-corpus.json")

# How far back the simulated feed looks, matching `feed_candidates`.
WINDOW_HOURS = 48


@dataclass
class Snapshot:
    """Everything a simulated ranking needs, and nothing it does not."""

    total_docs: int
    document_counts: dict[str, int]
    # cluster id -> raw term frequencies of its anchor
    vectors: dict[int, dict[str, float]] = field(default_factory=dict)
    # cluster id -> what a card would show
    cards: dict[int, dict] = field(default_factory=dict)
    # term -> [(neighbour, score)]
    edges: dict[str, list] = field(default_factory=dict)

    def clusters(self) -> list[int]:
        return sorted(self.vectors)


def _page(client, sql, params, size=5000):
    rows = []
    offset = 0
    while True:
        page = client.query(f"{sql} LIMIT ? OFFSET ?", [*params, size, offset])
        if not page:
            break
        rows.extend(page)
        offset += size
    return rows


def fetch(client: D1Client | None = None) -> Snapshot:
    """Reads the window, its terms, its metadata and the co-occurrence edges."""
    client = client or D1Client.from_env()

    total = client.query("SELECT total_docs FROM corpus_stats WHERE id = 1")[0]["total_docs"]

    cards = {}
    for row in _page(
        client,
        "SELECT f.cluster_id, f.published_at, s.name AS source, a.title, "
        "(SELECT COUNT(DISTINCT m.source_id) FROM articles m "
        " WHERE m.cluster_id = f.cluster_id) AS sources "
        "FROM feed_candidates f "
        "JOIN clusters c ON c.id = f.cluster_id "
        "JOIN articles a ON a.id = c.representative_article_id "
        "JOIN sources s ON s.id = a.source_id ORDER BY f.cluster_id",
        [],
    ):
        cards[row["cluster_id"]] = row

    vectors: dict[int, dict[str, float]] = {}
    for row in _page(
        client,
        "SELECT c.id AS cluster_id, t.term, t.tf "
        "FROM clusters c "
        "JOIN article_terms t ON t.article_id = c.representative_article_id "
        "JOIN feed_candidates f ON f.cluster_id = c.id ORDER BY c.id, t.term",
        [],
    ):
        vectors.setdefault(row["cluster_id"], {})[row["term"]] = row["tf"]

    counts = {}
    for row in _page(client, "SELECT term, doc_count FROM terms ORDER BY term", []):
        counts[row["term"]] = row["doc_count"]

    edges: dict[str, list] = {}
    for row in _page(
        client, "SELECT term_a, term_b, score FROM term_cooccur ORDER BY term_a", []
    ):
        edges.setdefault(row["term_a"], []).append((row["term_b"], row["score"]))

    return Snapshot(total, counts, vectors, cards, edges)


def load(client: D1Client | None = None, refresh: bool = False) -> Snapshot:
    """The snapshot, from disk when it is there."""
    if not refresh and os.path.exists(CACHE):
        raw = json.load(open(CACHE))
        return Snapshot(
            raw["total_docs"],
            raw["document_counts"],
            {int(k): v for k, v in raw["vectors"].items()},
            {int(k): v for k, v in raw["cards"].items()},
            raw["edges"],
        )

    snapshot = fetch(client)
    json.dump(
        {
            "total_docs": snapshot.total_docs,
            "document_counts": snapshot.document_counts,
            "vectors": snapshot.vectors,
            "cards": snapshot.cards,
            "edges": snapshot.edges,
        },
        open(CACHE, "w"),
    )
    return snapshot
