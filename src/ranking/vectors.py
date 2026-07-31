"""Sparse vector arithmetic, shared by the two runtimes.

Two places need this and they run nowhere near each other. The ingestion job
runs in GitHub Actions and uses it to cluster and to write `feed_candidates`;
the Worker runs on the edge and uses it to weigh a profile before asking the
database for a dot product. If each carried its own copy, a drift between them
would not raise anything. It would divide a dot product by a norm computed under
a different rule, and the feed would come back plausibly ordered and quietly
wrong.

So this module is the single definition, it lives under `src/` because that is
what the Worker bundles, and the ingestion reaches it through PYTHONPATH. Only
the standard library, for the same reason: a Python Worker gets 1000ms of
startup CPU and a third party import spends it.
"""

import math


def idf(doc_count: int, total_docs: int) -> float:
    """How much a term narrows the corpus down.

    The floor on `doc_count` covers a term the corpus has not counted yet, which
    is the normal case for new vocabulary during ingestion rather than an edge.
    An empty corpus returns zero for everything: IDF is corpus knowledge, and an
    empty corpus has none.

    Never materialized. IDF is a function of the whole corpus and shifts on
    every run, so a stored value would measure old documents on a different
    ruler than fresh ones.
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


def norm(vector: dict[str, float]) -> float:
    """Length of the vector.

    This is the number `feed_candidates.norm` holds, so that a request can turn
    the dot product the database gives it into a cosine without reading every
    term of every candidate back out.
    """
    return math.sqrt(sum(weight * weight for weight in vector.values()))


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine between two sparse vectors.

    The shorter vector drives the loop, so the work follows the overlap rather
    than the longer document.
    """
    smaller, larger = (a, b) if len(a) < len(b) else (b, a)
    dot = sum(weight * larger[term] for term, weight in smaller.items() if term in larger)
    if not dot:
        return 0.0

    magnitude = norm(a) * norm(b)
    return dot / magnitude if magnitude else 0.0


def strongest(vector: dict[str, float], limit: int) -> list[str]:
    """The terms carrying the most weight, strongest first.

    The feed query sends these and touches only the candidates that share one of
    them, which is what makes the work proportional to the overlap instead of to
    the archive. Ties break on the term itself so the choice is reproducible.
    """
    ranked = sorted(vector.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _ in ranked[:limit]]
