"""Decides which cluster an incoming article belongs to.

The `url UNIQUE` constraint only stops the same URL being read twice. The real
problem is that G1, BBC and CNN publish the same story under different URLs:

    "Copom mantem Selic em 10,5% ao ano"
    "Banco Central decide manter taxa Selic em 10,5%"
    "Selic: Copom mantem juros em 10,5%"

Ungrouped, those three take the top of the feed with tied scores, and liking one
pushes the other two up.

An arriving article is compared against the vector of the article that opened
each cluster still inside the window. That anchor is written once and never
rewritten, which is what stops a cluster from drifting: twenty stories about one
election would otherwise pull the centre toward generic terms until unrelated
coverage started falling in. It also leaves the card a reason it can state in
one line, "cosine 0.71 against the story that opened the group", which is the
kind of answer this project exists to be able to give.
"""

import math

# Deduplication compares IDF weighted vectors, not raw term frequencies. Under
# raw TF two stories that share only `presidente`, `governo` and `pais` look
# nearly identical, and those are exactly the terms with the highest document
# count. What separates one event from another is the terms that are rare.

# Calibrated against the 311 articles the corpus held on 2026-07-31, six portals
# across one 24 hour window, by running this algorithm at every threshold from
# 0.20 to 0.45 and reading every group it produced.
#
# Results were flat across [0.28, 0.30]: 17 groups, 11 of them spanning more
# than one portal, and no wrong merge among them. The edges are what fix the
# value inside that range rather than at either end of it.
#
#   0.27  "Unidade Popular oficializa candidaturas ao governo e Senado no Para"
#         merges with "PCdoB oficializa apoio a candidatura de Lula" at 0.272.
#         Different events sharing `oficializar`, `candidatura` and `partido`.
#
#   0.31  starts dropping real duplicates: Santander at 0.337, the Ceuta
#         migrants at 0.310, the Fifa thread at 0.301.
#
# So 0.30 keeps margin on both sides instead of sitting on a cliff. The number
# is a measurement, and it is expected to be measured again when the corpus is
# large enough for the IDF to have moved.
SIMILARITY_THRESHOLD = 0.30


def idf(doc_count: int, total_docs: int) -> float:
    """How much a term narrows the corpus down.

    The floor on `doc_count` covers a term this run is the first to see. Its
    count only rises after the writes, so without the floor the first appearance
    of every new term would divide by zero.

    On a corpus that is still empty this returns zero for everything, and a run
    against it groups nothing. That is the honest answer rather than a gap: IDF
    is corpus knowledge, and an empty corpus has none. The next hourly run has a
    corpus and clusters normally.
    """
    return math.log(max(total_docs, 1) / max(doc_count, 1))


def weigh(
    frequencies: dict[str, float],
    document_counts: dict[str, int],
    total_docs: int,
) -> dict[str, float]:
    """Scales each term frequency by how rare the term is in the corpus."""
    return {
        term: frequency * idf(document_counts.get(term, 0), total_docs)
        for term, frequency in frequencies.items()
    }


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine between two sparse vectors.

    The shorter vector drives the loop, so the work follows the overlap rather
    than the longer document.
    """
    smaller, larger = (a, b) if len(a) < len(b) else (b, a)
    dot = sum(weight * larger[term] for term, weight in smaller.items() if term in larger)
    if not dot:
        return 0.0

    magnitude = math.sqrt(sum(w * w for w in a.values())) * math.sqrt(
        sum(w * w for w in b.values())
    )
    return dot / magnitude if magnitude else 0.0


def assign_cluster(
    vector: dict[str, float],
    recent_clusters: list[tuple[int, dict[str, float]]],
) -> int | None:
    """Returns the cluster to attach to, or None to open a new one.

    `vector` and the anchors in `recent_clusters` must be weighted the same way,
    which is what `weigh` is for.

    The strongest match wins rather than the first one over the line. Taking the
    first would make the result depend on the order the window came back in, and
    SQLite does not promise one.
    """
    best_id = None
    best_score = 0.0

    for cluster_id, anchor in recent_clusters:
        score = cosine(vector, anchor)
        if score >= SIMILARITY_THRESHOLD and score > best_score:
            best_score = score
            best_id = cluster_id

    return best_id
