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

from api import expand, profile, session
from api.db import query
from ranking.score import (
    age_in_hours,
    discovery_lift,
    rejection,
    repetition,
    score,
    similarity,
)
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

# How much of a summary the card shows.
#
# What the feeds call a summary is not one thing. Measured across the corpus,
# The Register averages 84 characters and Engadget 113, while G1, Canaltech,
# IEEE and Agencia Brasil all sit at 595, which is the 600 character cap doing
# its work on what is really the article's body.
#
# Shown whole, half the sources would give a sentence and the other half seven
# lines of a paragraph cut mid word, and the card's height would encode which
# portal published it rather than what the story is. Clamped here, ten of the
# twenty sources pass through untouched and the rest are cut to the same shape.
#
# Clamped on the server rather than with CSS, because the client reports how much
# text was on screen so a dwell can be normalized by it, and text hidden by an
# overflow rule would inflate that number with words nobody read.
SUMMARY_CHARS = 220


def shorten(text: str, limit: int = SUMMARY_CHARS) -> str:
    """A summary cut to a readable length, on a word boundary.

    Mid word is worse than short: the reader sees a fragment and the ellipsis
    lands inside a name.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text

    cut = text[:limit]
    boundary = cut.rfind(" ")
    return (cut[:boundary] if boundary > 0 else cut).rstrip(" ,;:") + "…"


async def corpus_size(env) -> int:
    row = await query(env, "SELECT total_docs FROM corpus_stats WHERE id = 1")
    return row[0]["total_docs"] if row else 0


async def contributions(
    env, weighted: dict[str, float], factors: dict[str, float]
) -> dict[int, dict[str, float]]:
    """How much each profile term contributes to each candidate.

    Returns cluster id to term to contribution. Summing the inner dict gives the
    dot product; sorting it gives the reason.

    What gets bound per term is the profile weight times that term's IDF again,
    and the second IDF is the candidate's, not a repetition. `article_terms`
    stores raw TF, so the product the database computes is
    `tf_candidato * (tf_perfil * idf * idf)`, which regroups into
    `(tf_candidato * idf) * (tf_perfil * idf)`: both sides weighed once, which is
    the numerator of a cosine whose denominator is already measured that way.

    Binding only the profile weight left the candidate unweighted while
    `feed_candidates.norm` was not, and the error was not a scale factor that
    cancels. Against the live window it ran from 3.1x to 7.2x depending on which
    terms matched, which compresses every candidate into a narrow band and lets
    a story matching on `tecnico` the school subject outrank one matching on
    `tecnico` the football coach.
    """
    terms = strongest(weighted, PROFILE_TERMS)
    if not terms:
        return {}

    cases = " ".join(["WHEN ? THEN ?"] * len(terms))
    placeholders = ", ".join("?" * len(terms))
    params = [
        value for term in terms for value in (term, weighted[term] * factors.get(term, 0.0))
    ] + terms

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
    """The window the ingestion published, ordered so a tie falls to the fresher.

    `sources` comes along because a discovery slot needs it, and joining it here
    costs one aggregate over rows the query already walks. Asking separately
    would mean a second pass over the same window to answer a question about the
    same rows.
    """
    return await query(
        env,
        "SELECT f.cluster_id, f.base_score, f.norm, f.published_at, f.top_terms, "
        "(SELECT COUNT(DISTINCT a.source_id) FROM articles a "
        " WHERE a.cluster_id = f.cluster_id) AS sources "
        "FROM feed_candidates f ORDER BY f.base_score DESC",
    )


def interleave(everything, offset: int, size: int = PAGE):
    """One page of what `scored` produced.

    Nothing is reserved here any more. Coverage used to buy a fixed share of the
    positions, filled at a stride of `round(1 / ratio)`, and the stride was
    visible: at half the page it was one story in two, which reads as a mechanism
    rather than as a feed. Worse, the count of marked stories was decided by the
    slider, so the badge could only ever repeat a choice the reader had just
    made.

    Coverage now competes inside the score, so a story arriving by that route
    arrived by outranking the others, and the page is a page.
    """
    return everything[offset : offset + size]


def rank(
    rows,
    matched,
    profile_norm,
    answered,
    now,
    avoided=None,
    avoided_norm=0.0,
    offset=0,
    shown=None,
    session=None,
    session_norm=0.0,
    session_weight=0.0,
    adjacent=None,
    adjacent_norm=0.0,
    discovery_ratio=0.0,
) -> list[dict]:
    """One page of what `scored` produced.

    Paging by offset rather than by a cursor on the score, and that is safe here
    for a reason particular to this corpus: the ranking only moves when the
    ingestion runs, once an hour. Between two runs the order is fixed, so page
    two is the same list page one came from, further down.
    """
    everything = scored(
        rows,
        matched,
        profile_norm,
        answered,
        now,
        avoided,
        avoided_norm,
        shown,
        session,
        session_norm,
        session_weight,
        adjacent,
        adjacent_norm,
        discovery_ratio,
    )
    return interleave(everything, offset)


def scored(
    rows,
    matched,
    profile_norm,
    answered,
    now,
    avoided=None,
    avoided_norm=0.0,
    shown=None,
    session=None,
    session_norm=0.0,
    session_weight=0.0,
    adjacent=None,
    adjacent_norm=0.0,
    discovery_ratio=0.0,
) -> list[dict]:
    """Scores every candidate and returns all of them, best first.

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
    shown = shown or {}
    session = session or {}
    adjacent = adjacent or {}
    ranked = []

    for row in rows:
        cluster_id = row["cluster_id"]
        if cluster_id in answered:
            continue

        # Offered enough times already. Dropped here rather than scored to zero,
        # so it cannot occupy a slot on a page it can never win.
        seen = shown.get(cluster_id, 0)
        damping = repetition(seen)
        if not damping:
            continue

        terms = matched.get(cluster_id, {})
        against = avoided.get(cluster_id, {})

        current = session.get(cluster_id, {})

        affinity = similarity(sum(terms.values()), profile_norm, row["norm"])
        penalty = rejection(similarity(sum(against.values()), avoided_norm, row["norm"]))
        momentum = similarity(sum(current.values()), session_norm, row["norm"])
        nearby = similarity(
            sum(adjacent.get(cluster_id, {}).values()), adjacent_norm, row["norm"]
        )
        age = age_in_hours(row["published_at"], now)

        # What coverage is worth here, and the reason the badge can name itself.
        # Zero unless the reader asked for some, more than one portal ran it, and
        # the profile has nothing to say about it.
        lift = discovery_lift(affinity, row.get("sources", 1), discovery_ratio)

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
                "score": score(
                    affinity, age, penalty, momentum, session_weight, nearby, lift
                )
                * damping,
                "similarity": affinity,
                "discovery": lift > 0,
                "penalty": penalty,
                "momentum": momentum,
                "nearby": nearby,
                "shown": seen,
                "sources": row.get("sources", 1),
                "age_hours": age,
                "because": [term for term, _ in sorted(terms.items(), key=_by_weight)][:REASONS],
                "against": blamed,
                "about": _parse_terms(row["top_terms"]),
            }
        )

    ranked.sort(key=lambda card: -card["score"])
    return ranked


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

    # The left join is what lets the chronological and search lists share this
    # function. Their clusters carry no score and no reason, but the terms the
    # ingestion already wrote are worth showing, and a cluster older than the
    # ranking window simply has no row there and no kicker.
    anchors = await query(
        env,
        "SELECT c.id AS cluster_id, c.size, a.title, a.summary, a.url, "
        "a.published_at, s.name AS source, f.top_terms AS top_terms "
        "FROM clusters c "
        "JOIN articles a ON a.id = c.representative_article_id "
        "JOIN sources s ON s.id = a.source_id "
        "LEFT JOIN feed_candidates f ON f.cluster_id = c.id "
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
                "because": [],
                "against": [],
                "about": _parse_terms(anchor["top_terms"]),
                **card,
                "title": anchor["title"],
                "summary": shorten(anchor["summary"]),
                "url": anchor["url"],
                "source": anchor["source"],
                "published_at": anchor["published_at"],
                "size": anchor["size"],
                "also_in": others,
            }
        )

    return cards


async def build(
    env,
    profile_vector,
    negative_vector,
    answered,
    now,
    offset=0,
    shown=None,
    session_vector=None,
    session_clusters=None,
    discovery_ratio=0.0,
) -> list[dict]:
    """One page of one reader's feed, from stored profiles to finished cards.

    An empty vector skips its index query entirely: there are no terms to send,
    the cosine is zero either way, and what survives in the formula is the
    recency floor. Both sides are guarded that way, and the two guards matter at
    different times. The positive one is the path most visitors take, since
    everyone arrives having liked nothing. The negative one is the path almost
    everyone stays on, because hiding is the rarer gesture, so the second query
    is one a typical request never issues.
    """
    total_docs = await corpus_size(env)

    weighted, kept_idf = await profile.weighted(env, profile_vector, total_docs)
    avoided, avoided_idf = await profile.weighted(env, negative_vector, total_docs)
    current, current_idf = await profile.weighted(env, session_vector or {}, total_docs)

    # The reader's adjacent subjects, built from the corpus's own co-occurrence
    # rather than from anybody else's behaviour. Skipped entirely for a visitor
    # who has said nothing, which is the common path.
    reach = await expand.build(env, profile_vector) if profile_vector else {}
    nearby, nearby_idf = await profile.weighted(env, reach, total_docs)

    matched = await contributions(env, weighted, kept_idf) if weighted else {}
    against = await contributions(env, avoided, avoided_idf) if avoided else {}
    momentum = await contributions(env, current, current_idf) if current else {}
    adjacent = await contributions(env, nearby, nearby_idf) if nearby else {}

    page = rank(
        await candidates(env),
        matched,
        norm(weighted),
        answered,
        now,
        against,
        norm(avoided),
        offset,
        shown,
        momentum,
        norm(current),
        session.weight(session_clusters or []),
        adjacent,
        norm(nearby),
        discovery_ratio,
    )

    return await decorate(env, page)
