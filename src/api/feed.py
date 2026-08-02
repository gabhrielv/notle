"""Assembles the ranked feed for one reader.

The dot product happens in the database. With profile vectors serialized as JSON
and cluster vectors spread across `article_terms`, doing it here would mean
pulling every candidate's terms into the Worker and parsing them, which grows
with the archive and is paid in exactly the currency serverless charges.

Sending the strongest profile terms instead means the index on
`article_terms(term)` is what decides which candidates are touched at all, so the
work follows the overlap between a reader and the day's news rather than the
size of the corpus.

The aggregation is grouped by cluster and term, not just by cluster. Splitting it
per term costs nothing, because those are the rows the index already walked, and
it is what lets a card say which terms put it where it is. The explanation is the
arithmetic of the position rather than a story assembled afterwards.
"""

import json

from api import profile
from api.db import query
from ranking.score import age_in_hours, rejection, score, similarity
from ranking.vectors import norm, strongest

# How many profile terms reach the query. Twenty covers the shape of a taste
# while leaving room under the 100 parameter ceiling: each term is bound twice
# in the CASE and once in the IN.
PROFILE_TERMS = 20

# How many cards a request returns. Enough to scroll, small enough that the
# detail lookups stay one round trip each.
PAGE = 24

# How many terms of a card's reason are worth showing. More than three stops
# being a reason and starts being a dump.
REASONS = 3


async def corpus_size(env) -> int:
    row = await query(env, "SELECT total_docs FROM corpus_stats WHERE id = 1")
    return row[0]["total_docs"] if row else 0


async def contributions(env, weighted: dict[str, float]) -> dict[int, dict[str, float]]:
    """How much each profile term contributes to each candidate.

    Returns cluster id to term to contribution. Summing the inner dict gives the
    dot product; sorting it gives the reason.
    """
    terms = strongest(weighted, PROFILE_TERMS)
    if not terms:
        return {}

    cases = " ".join(["WHEN ? THEN ?"] * len(terms))
    placeholders = ", ".join("?" * len(terms))
    params = [value for term in terms for value in (term, weighted[term])] + terms

    rows = await query(
        env,
        "SELECT f.cluster_id, t.term, "
        f"SUM(t.tf * CASE t.term {cases} ELSE 0 END) AS contribution "
        "FROM feed_candidates f "
        "JOIN clusters c ON c.id = f.cluster_id "
        "JOIN article_terms t ON t.article_id = c.representative_article_id "
        f"WHERE t.term IN ({placeholders}) "
        "GROUP BY f.cluster_id, t.term",
        params,
    )

    matched: dict[int, dict[str, float]] = {}
    for row in rows:
        matched.setdefault(row["cluster_id"], {})[row["term"]] = row["contribution"]
    return matched


async def candidates(env) -> list[dict]:
    """The window the ingestion published, ordered so a tie falls to the fresher."""
    return await query(
        env,
        "SELECT cluster_id, base_score, norm, published_at, top_terms "
        "FROM feed_candidates ORDER BY base_score DESC",
    )


def rank(
    rows, matched, profile_norm, answered, now, avoided=None, avoided_norm=0.0
) -> list[dict]:
    """Scores every candidate and returns a page of them, best first.

    A cluster the reader already answered for is dropped rather than scored,
    whether they kept it or hid it. Hiding it is the obvious half. Keeping it
    matters for a less obvious reason: the profile was built from that cluster's
    own terms, so it matches itself better than anything else can and would sit
    at the top of every feed from then on.

    Every card leaves with both sides of its position named: `because` holds the
    profile terms that lifted it, `against` the hidden ones that pushed it down.
    Both fall out of the same aggregation that produced the number, so what the
    screen says is the arithmetic itself rather than a story told about it
    afterwards.
    """
    avoided = avoided or {}
    ranked = []

    for row in rows:
        cluster_id = row["cluster_id"]
        if cluster_id in answered:
            continue

        terms = matched.get(cluster_id, {})
        against = avoided.get(cluster_id, {})

        affinity = similarity(sum(terms.values()), profile_norm, row["norm"])
        penalty = rejection(similarity(sum(against.values()), avoided_norm, row["norm"]))
        age = age_in_hours(row["published_at"], now)

        # A resemblance the ranking refused to act on is one the card must not
        # claim either, or the screen would name a reason worth nothing.
        blamed = (
            [term for term, _ in sorted(against.items(), key=_by_weight)][:REASONS]
            if penalty
            else []
        )

        ranked.append(
            {
                "cluster_id": cluster_id,
                "score": score(affinity, age, penalty),
                "similarity": affinity,
                "penalty": penalty,
                "age_hours": age,
                "because": [term for term, _ in sorted(terms.items(), key=_by_weight)][:REASONS],
                "against": blamed,
                "about": _parse_terms(row["top_terms"]),
            }
        )

    ranked.sort(key=lambda card: -card["score"])
    return ranked[:PAGE]


def _by_weight(item):
    term, contribution = item
    return (-contribution, term)


def _parse_terms(raw):
    try:
        parsed = json.loads(raw or "[]")
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


async def decorate(env, ranked: list[dict]) -> list[dict]:
    """Attaches what a card shows: the headline, where it points, who else ran it.

    Two queries for the whole page rather than two per card. The anchor supplies
    the headline and the link, because it is the article the group was matched
    against and the one whose terms explain the position.
    """
    if not ranked:
        return []

    ids = [card["cluster_id"] for card in ranked]
    placeholders = ", ".join("?" * len(ids))

    anchors = await query(
        env,
        "SELECT c.id AS cluster_id, c.size, a.title, a.url, a.published_at, s.name AS source "
        "FROM clusters c "
        "JOIN articles a ON a.id = c.representative_article_id "
        "JOIN sources s ON s.id = a.source_id "
        f"WHERE c.id IN ({placeholders})",
        ids,
    )
    by_cluster = {row["cluster_id"]: row for row in anchors}

    covered = await query(
        env,
        "SELECT DISTINCT a.cluster_id, s.name "
        "FROM articles a JOIN sources s ON s.id = a.source_id "
        f"WHERE a.cluster_id IN ({placeholders})",
        ids,
    )
    sources: dict[int, list[str]] = {}
    for row in covered:
        sources.setdefault(row["cluster_id"], []).append(row["name"])

    cards = []
    for card in ranked:
        anchor = by_cluster.get(card["cluster_id"])
        if anchor is None:
            # The window moved under the request: the ingestion rebuilt
            # `feed_candidates` between the two reads. Dropping the card is
            # right, since there is nothing left to show for it.
            continue

        covering = sources.get(card["cluster_id"], [])
        others = sorted(name for name in covering if name != anchor["source"])
        cards.append(
            {
                **card,
                "title": anchor["title"],
                "url": anchor["url"],
                "source": anchor["source"],
                "published_at": anchor["published_at"],
                "size": anchor["size"],
                "also_in": others,
            }
        )

    return cards


async def build(env, profile_vector, negative_vector, answered, now) -> list[dict]:
    """One reader's feed, from stored profiles to finished cards.

    An empty vector skips its index query entirely: there are no terms to send,
    the cosine is zero either way, and what survives in the formula is the
    recency floor. Both sides are guarded that way, and the two guards matter at
    different times. The positive one is the path most visitors take, since
    everyone arrives having liked nothing. The negative one is the path almost
    everyone stays on, because hiding is the rarer gesture, so the second query
    is one a typical request never issues.
    """
    total_docs = await corpus_size(env)

    weighted = await profile.weighted(env, profile_vector, total_docs)
    avoided = await profile.weighted(env, negative_vector, total_docs)

    matched = await contributions(env, weighted) if weighted else {}
    against = await contributions(env, avoided) if avoided else {}

    ranked = rank(
        await candidates(env),
        matched,
        norm(weighted),
        answered,
        now,
        against,
        norm(avoided),
    )
    return await decorate(env, ranked)
