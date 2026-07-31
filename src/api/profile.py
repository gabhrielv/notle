"""Builds the taste vector from the log of what a reader did.

The stored vector is a cache, not a source. It is rebuilt from `interactions`
every time one is recorded, so it stays a pure function of the log: a write that
fails leaves the log short by one event and the next event repairs the vector,
instead of leaving a profile that is wrong forever with nothing to point at it.

That is also what the architecture means by interactions being events and never
flags. The same rows get read with a different time constant later to produce the
session profile, and with a different lens again to produce the negative one.
Neither is possible if a like has already been folded into a number and thrown
away.
"""

import json
from datetime import UTC, datetime

from api.db import MAX_BOUND_PARAMS, execute, query
from ranking.vectors import weigh

# What each explicit signal is worth. Slice 1 only records two of them; the rest
# of the funnel arrives later and lands in the same table.
WEIGHTS = {"like": 1.0, "save": 1.2, "share": 1.5}

POSITIVE = tuple(WEIGHTS)

# Signals the reader chose to send. Implicit ones (impression, dwell, the time
# spent away) arrive in a later slice and are deliberately not in this tuple:
# they adjust, they do not decide.
EXPLICIT = (*POSITIVE, "hide")


def combine(vectors: list[tuple[dict[str, float], float]]) -> dict[str, float]:
    """Weighted mean of the term vectors of the clusters a reader kept.

    A mean rather than a sum, so that a reader with forty likes does not get a
    vector forty times longer than a reader with one. Length would not change
    the cosine, but it would change how a like compares against the recency
    floor, and the floor is a fixed number.
    """
    total_weight = sum(weight for _, weight in vectors)
    if not total_weight:
        return {}

    combined: dict[str, float] = {}
    for vector, weight in vectors:
        share = weight / total_weight
        for term, frequency in vector.items():
            combined[term] = combined.get(term, 0.0) + frequency * share

    return combined


async def positive_vectors(env, user_id: str) -> list[tuple[dict[str, float], float]]:
    """The anchor terms of every cluster this reader kept, with the signal weight.

    One query rather than one per interaction. The join reaches the cluster's
    anchor, which is the same article the clustering matched against and the
    same one `feed_candidates` was measured from, so a profile and a candidate
    are always described in the same vocabulary.
    """
    placeholders = ", ".join("?" * len(POSITIVE))
    rows = await query(
        env,
        "SELECT i.cluster_id, i.type, t.term, t.tf "
        "FROM interactions i "
        "JOIN clusters c ON c.id = i.cluster_id "
        "JOIN article_terms t ON t.article_id = c.representative_article_id "
        f"WHERE i.user_id = ? AND i.type IN ({placeholders})",
        [user_id, *POSITIVE],
    )

    grouped: dict[int, tuple[dict[str, float], float]] = {}
    for row in rows:
        vector, _ = grouped.setdefault(row["cluster_id"], ({}, WEIGHTS[row["type"]]))
        vector[row["term"]] = row["tf"]

    return list(grouped.values())


async def hidden_clusters(env, user_id: str) -> set[int]:
    """Clusters this reader asked not to see again.

    Slice 1 treats `hide` as an exclusion and nothing more. Slice 3 reads these
    same rows again to build a negative vector, which is what lets a card say
    why it ranked lower instead of simply vanishing.
    """
    rows = await query(
        env,
        "SELECT DISTINCT cluster_id FROM interactions WHERE user_id = ? AND type = 'hide'",
        [user_id],
    )
    return {row["cluster_id"] for row in rows if row["cluster_id"] is not None}


async def acted_on(env, user_id: str) -> set[int]:
    """Every cluster this reader has already answered for, either way.

    The feed leaves these out, and the reason is not politeness about repeats.
    A liked cluster is the strongest possible match against a profile that was
    built from its own terms, so it returns to the top scoring several times
    everything else, and it stays there. That is not a preference the reader
    expressed; it is the vector recognising itself.

    Only explicit signals count here. Slice 5 brings impressions, which measure
    what the ranking chose to show rather than what the reader thought of it,
    and folding those in would hide an article for the crime of having been
    displayed.
    """
    placeholders = ", ".join("?" * len(EXPLICIT))
    rows = await query(
        env,
        "SELECT DISTINCT cluster_id FROM interactions "
        f"WHERE user_id = ? AND type IN ({placeholders})",
        [user_id, *EXPLICIT],
    )
    return {row["cluster_id"] for row in rows if row["cluster_id"] is not None}


async def rebuild(env, user_id: str) -> dict[str, float]:
    """Recomputes the stored vector from the log and writes it back."""
    vector = combine(await positive_vectors(env, user_id))

    await execute(
        env,
        "UPDATE user_profile SET term_vector = ?, updated_at = ? WHERE user_id = ?",
        [
            json.dumps(vector, ensure_ascii=False),
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            user_id,
        ],
    )
    return vector


async def load(env, user_id: str) -> dict[str, float]:
    """Reads the cached vector. Raw frequencies, never weighted.

    Storing it already weighted would freeze an IDF that moves on every
    ingestion run, which is the same mistake the corpus avoids by keeping raw TF
    in `article_terms`. The weighing happens per request, against the corpus
    that exists then.
    """
    rows = await query(
        env,
        "SELECT term_vector FROM user_profile WHERE user_id = ?",
        [user_id],
    )
    if not rows:
        return {}

    try:
        stored = json.loads(rows[0]["term_vector"] or "{}")
    except ValueError:
        return {}

    return stored if isinstance(stored, dict) else {}


async def weighted(env, vector: dict[str, float], total_docs: int) -> dict[str, float]:
    """Applies the IDF of this moment to a stored profile.

    Read in chunks because D1 binds at most 100 parameters per statement, and a
    reader with a few dozen likes carries more distinct terms than that. The
    profile is not capped here: which terms matter is a question about weights,
    and the weights are what this is on its way to computing.
    """
    if not vector:
        return {}

    terms = sorted(vector)
    counts: dict[str, int] = {}
    for start in range(0, len(terms), MAX_BOUND_PARAMS):
        chunk = terms[start : start + MAX_BOUND_PARAMS]
        placeholders = ", ".join("?" * len(chunk))
        rows = await query(
            env,
            f"SELECT term, doc_count FROM terms WHERE term IN ({placeholders})",
            chunk,
        )
        counts.update({row["term"]: row["doc_count"] for row in rows})

    return weigh(vector, counts, total_docs)
