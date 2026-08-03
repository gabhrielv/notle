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
from ranking.vectors import idf, weigh

# What each explicit signal is worth. Slice 1 only records two of them; the rest
# of the funnel arrives later and lands in the same table.
# `seed` is what the onboarding records, and it is kept apart from `like` even
# though both weigh 1.0 and both land in the same vector. Choosing among twelve
# headlines in a form is not the gesture of keeping a story while reading, and
# the architecture's line on interactions being events rather than flags is
# exactly about not throwing that distinction away: once the two are written as
# one type, no later slice can ask whether a seed predicts taste as well as a
# like does, which is a question the persona simulator is meant to answer.
POSITIVE_WEIGHTS = {"seed": 1.0, "like": 1.0, "save": 1.2, "share": 1.5}

# Hiding is kept apart rather than entered as a negative number in the same
# vector, and the reason is arithmetic. With one signed vector the decay
# multiplies the whole thing, so two unwanted stories at cosine -0.5 come out at
# -0.485 after an hour and -0.063 after three days: the ranking prefers the
# older of two things the reader rejected. Worse, a story about something wholly
# unknown sits at exactly zero and floats above both. Two vectors keep every
# cosine in [0, 1], the decay only ever multiplies something positive, and the
# inversion disappears.
NEGATIVE_WEIGHTS = {"hide": 1.0}

WEIGHTS = {**POSITIVE_WEIGHTS, **NEGATIVE_WEIGHTS}

# The implicit half of the funnel. Weighed per event rather than per type, so
# their weights live in `api.signals` and reach the database in the `value`
# column instead of in a table here.
#
# `impression` is deliberately in neither tuple. It is stored, because the
# ranking counts it to stop offering a story a fourth time, and it is never read
# into a profile, because it measures what the ranking chose to show rather than
# what the reader thought of it.
IMPLICIT_POSITIVE = ("dwell", "click", "return")

POSITIVE = (*POSITIVE_WEIGHTS, *IMPLICIT_POSITIVE)
NEGATIVE = tuple(NEGATIVE_WEIGHTS)

# Signals the reader chose to send. Implicit ones (impression, dwell, the time
# spent away) arrive in a later slice and are deliberately not in this tuple:
# they adjust, they do not decide.
EXPLICIT = (*POSITIVE, *NEGATIVE)

# How long a signal keeps half its weight in the long profile.
#
# The architecture's table of the four vectors gives this one a time constant of
# months, and until now the code implemented none: a like from a year ago
# weighed exactly as much as one from a minute ago, so a profile accumulated
# forever and nothing a reader stopped caring about ever left it.
#
# Sixty days is what "months" means at the coarsest reading that still moves.
# A taste from last week arrives essentially whole, one from a season ago at a
# quarter, and one from a year ago at 1.5%, which is gone without ever being
# deleted. The reader is never told a preference expired, because it did not:
# it faded, which is what the constant says it should do.
#
# Note that the persona simulator cannot see this. It compresses every
# interaction into one instant, so every decay factor there is exactly 1. This
# is a correction to the specification rather than a result from the grid, and
# it is recorded as such.
LONG_HALF_LIFE_DAYS = 60.0


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


async def signal_vectors(
    env, user_id: str, kinds: tuple[str, ...], now=None
) -> list[tuple[dict[str, float], float]]:
    """The anchor terms of every cluster this reader answered one way, weighted.

    One query rather than one per interaction. The join reaches the cluster's
    anchor, which is the same article the clustering matched against and the
    same one `feed_candidates` was measured from, so a profile and a candidate
    are always described in the same vocabulary.

    Both directions read the same table through this one function. That is what
    the architecture means by interactions being events rather than flags: a
    like and a hide are the same row shape, and which vector they land in is a
    question asked at read time.

    The weight comes from `interactions.value` rather than from a table keyed on
    type, because the implicit half of the funnel does not have one weight per
    type: what a dwell is worth depends on how long it lasted against how much
    text there was. Summing the column also means several signals on one cluster
    accumulate, which is the point of a funnel whose stages filter each other.

    A cluster whose signals cancel to zero or below is dropped. That happens when
    a click was followed by an immediate return, and the honest reading of that
    pair is that the reader looked and left, not that they were interested a
    little.

    Each cluster's weight fades with how long ago it was answered, at the half
    life the architecture gives this vector. The session profile reads the same
    rows through a ten minute half life; this one reads them through sixty days.
    Same log, two time constants, which is the whole reason interactions are
    stored as events rather than folded into a number.
    """
    placeholders = ", ".join("?" * len(kinds))
    rows = await query(
        env,
        "SELECT i.cluster_id, SUM(i.value) AS weight, MAX(i.created_at) AS last_at, "
        "t.term, t.tf "
        "FROM interactions i "
        "JOIN clusters c ON c.id = i.cluster_id "
        "JOIN article_terms t ON t.article_id = c.representative_article_id "
        f"WHERE i.user_id = ? AND i.type IN ({placeholders}) "
        "GROUP BY i.cluster_id, t.term",
        [user_id, *kinds],
    )

    now = (now or datetime.now(UTC)).timestamp()
    grouped: dict[int, tuple[dict[str, float], float]] = {}

    for row in rows:
        cluster_id = row["cluster_id"]
        if cluster_id not in grouped:
            grouped[cluster_id] = ({}, faded(row["weight"] or 0.0, row["last_at"], now))
        grouped[cluster_id][0][row["term"]] = row["tf"]

    return [pair for pair in grouped.values() if pair[1] > 0]


def faded(weight: float, last_at: str, now: float) -> float:
    """A signal's weight, reduced by how long ago it was given.

    An unreadable timestamp is treated as just now rather than as infinitely
    old. Losing the date of one interaction should cost its age, not the signal
    itself.
    """
    if weight <= 0:
        return 0.0

    try:
        seen = datetime.fromisoformat(last_at).timestamp()
    except (TypeError, ValueError):
        return weight

    days = max(now - seen, 0.0) / 86400.0
    return weight * 0.5 ** (days / LONG_HALF_LIFE_DAYS)


async def positive_vectors(env, user_id: str, now=None):
    """Clusters the reader kept, or read, or clicked through to."""
    return await signal_vectors(env, user_id, POSITIVE, now)


async def negative_vectors(env, user_id: str, now=None):
    """Clusters the reader hid.

    Slice 1 treated a hide as an exclusion and nothing more, so the reader's
    strongest statement about what they do not want shaped exactly one card.
    Read as a vector it reaches everything that resembles it, which is what
    lets a card say why it ranked lower instead of a subject simply vanishing.
    """
    return await signal_vectors(env, user_id, NEGATIVE, now)


async def hidden(env, user_id: str) -> set[int]:
    """Only the clusters the reader asked not to see.

    The chronological list needs this half on its own, where the feed needs
    `acted_on`. A liked cluster is left out of the feed because a profile built
    from its terms recognises itself and pins it to the top forever, which is an
    argument about ranking. Nothing ranks here, so a story stays in the timeline
    on the strength of having been liked.
    """
    placeholders = ", ".join("?" * len(NEGATIVE))
    rows = await query(
        env,
        "SELECT DISTINCT cluster_id FROM interactions "
        f"WHERE user_id = ? AND type IN ({placeholders})",
        [user_id, *NEGATIVE],
    )
    return {row["cluster_id"] for row in rows if row["cluster_id"] is not None}


async def impressions(env, user_id: str) -> dict[int, int]:
    """How many times each cluster has already been offered to this reader.

    The one thing an impression is read for. It never reaches a vector, because
    a story appearing is a consequence of the ranking's own choice rather than
    anything the reader thought, and a system that learns from it is measuring
    its own output.
    """
    rows = await query(
        env,
        "SELECT cluster_id, COUNT(*) AS shown FROM interactions "
        "WHERE user_id = ? AND type = 'impression' AND cluster_id IS NOT NULL "
        "GROUP BY cluster_id",
        [user_id],
    )
    return {row["cluster_id"]: row["shown"] for row in rows}


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


async def rebuild(env, user_id: str) -> tuple[dict[str, float], dict[str, float]]:
    """Recomputes both stored vectors from the log and writes them back.

    Both, on every signal, even though one interaction can only have moved one
    of them. Rewriting the pair costs a second read of a table the reader has a
    handful of rows in, and it keeps the invariant that matters: what is stored
    is a pure function of the log at one moment, rather than two caches that
    were last correct at different times.
    """
    positive = combine(await positive_vectors(env, user_id))
    negative = combine(await negative_vectors(env, user_id))

    await execute(
        env,
        "UPDATE user_profile SET term_vector = ?, neg_term_vector = ?, updated_at = ? "
        "WHERE user_id = ?",
        [
            json.dumps(positive, ensure_ascii=False),
            json.dumps(negative, ensure_ascii=False),
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            user_id,
        ],
    )
    return positive, negative


def _decode(raw) -> dict[str, float]:
    """A stored vector, or an empty one if the column is not readable JSON."""
    try:
        stored = json.loads(raw or "{}")
    except ValueError:
        return {}

    return stored if isinstance(stored, dict) else {}


async def load(env, user_id: str) -> tuple[dict[str, float], dict[str, float]]:
    """Reads both cached vectors. Raw frequencies, never weighted.

    Storing them already weighted would freeze an IDF that moves on every
    ingestion run, which is the same mistake the corpus avoids by keeping raw TF
    in `article_terms`. The weighing happens per request, against the corpus
    that exists then.

    One query for the pair, because they are two columns of one row and the feed
    needs both before it can rank anything.
    """
    rows = await query(
        env,
        "SELECT term_vector, neg_term_vector FROM user_profile WHERE user_id = ?",
        [user_id],
    )
    if not rows:
        return {}, {}

    return _decode(rows[0]["term_vector"]), _decode(rows[0]["neg_term_vector"])


async def weighted(
    env, vector: dict[str, float], total_docs: int
) -> tuple[dict[str, float], dict[str, float]]:
    """Applies the IDF of this moment to a stored profile.

    Returns the weighted vector and the IDF that produced it, per term. The
    second is not a convenience: the dot product happens in SQL against the raw
    TF the corpus stores, so the value bound per term has to carry the
    candidate's share of the weighing as well as the profile's. Handing back the
    factor is what lets the caller do that without asking the database for
    document counts a second time.

    Read in chunks because D1 binds at most 100 parameters per statement, and a
    reader with a few dozen likes carries more distinct terms than that. The
    profile is not capped here: which terms matter is a question about weights,
    and the weights are what this is on its way to computing.
    """
    if not vector:
        return {}, {}

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

    factors = {term: idf(counts.get(term, 0), total_docs) for term in vector}
    return weigh(vector, counts, total_docs), factors
