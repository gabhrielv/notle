"""The reader's last few minutes, read out of the same log as everything else.

No new table and no new events. The session profile is `interactions` filtered
by `session_id`, with each row's contribution decayed by how long ago it
happened. Three signals about the economy inside ninety seconds stack three
nearly whole contributions; the same three spread over an hour arrive at almost
nothing. How fast someone is reading falls out of the arithmetic, with no code
anywhere that computes a rate.

Two locks the architecture puts on it, both enforced here.

It dies with the session. The id comes from the tab and is never written to
`user_profile`, so a curious afternoon about football cannot become a permanent
identity.

Its weight is adaptive and capped. Without the cap, three taps on sport convert
the rest of the session into sport, because the reinforcement produces more
engagement which produces more reinforcement. It is the same vicious loop as the
impression, running in minutes instead of weeks.
"""

from datetime import datetime

from api.db import query
from ranking.vectors import cosine

# How long a signal keeps half its weight in this reading of the log.
#
# Ten minutes is short enough that the vector is about what the reader is doing
# rather than what they did, and long enough to survive reading one article. It
# is also why a tab left open all afternoon costs nothing: a signal from two
# hours back arrives at under a percent.
HALF_LIFE_MINUTES = 10.0

# Where the ramp from no weight to full weight begins and ends.
#
# Both read off real sessions rather than chosen. Three clusters about one event,
# Lula's convention across three portals, resembled each other at 0.287. Three
# unrelated ones, a football transfer, a festival announcement and a health
# story, sat at 0.068. A mixed session, two about one thing and one loose, landed
# at 0.098, between them.
#
# The first measure tried here was normalised entropy over the session's term
# vector, on the argument that it captures how spread out a taste is. Against
# those same three sessions it produced 0.0584, 0.0589 and 0.0327: no separation
# at all between focused and scattered, and the mixed case ranked below both.
# Three whole articles carry around eighty terms whatever they are about, so the
# shape of that vector says almost nothing about whether they were about one
# thing.
#
# Resemblance between the clusters says it directly, which is also what the
# architecture means by a run on one subject.
FOCUS_FLOOR = 0.05
FOCUS_FULL = 0.30

# The most the session may ever be worth against the long profile.
#
# The cap is the whole point rather than a safety margin. Session affinity is
# measured on the same scale as the long profile's, so an uncapped weight would
# let the last ten minutes outvote everything the reader has ever said.
MAX_WEIGHT = 0.35

# Signals recent enough to still carry weight. Six half lives leaves under two
# percent, which is below the resolution of anything downstream, so reading
# further back would cost rows to change nothing.
WINDOW_MINUTES = 60.0


def focus(vectors: list[dict[str, float]]) -> float:
    """How much the session's clusters resemble each other, in [0, 1].

    The mean cosine over every pair. Quadratic in the number of clusters, which
    costs nothing: a session is under ten of them, and the window drops anything
    older than an hour.

    One cluster is not a run. There is no pair to compare, and calling a single
    story a focused session would hand the cap to anyone who read one thing.
    """
    if len(vectors) < 2:
        return 0.0

    pairs = [
        cosine(a, b)
        for index, a in enumerate(vectors)
        for b in vectors[index + 1 :]
    ]
    return sum(pairs) / len(pairs)


def weight(vectors: list[dict[str, float]]) -> float:
    """How much this session is allowed to say, from how focused it is.

    Scattered reading zeroes itself, which is what makes the weight adaptive
    rather than a constant somebody has to remember to switch off.
    """
    span = FOCUS_FULL - FOCUS_FLOOR
    share = (focus(vectors) - FOCUS_FLOOR) / span
    return MAX_WEIGHT * min(max(share, 0.0), 1.0)


def decayed(vectors: list[tuple[dict[str, float], float, float]]) -> dict[str, float]:
    """Folds the session's clusters into one vector, older signals counting less.

    `vectors` is (terms, signal weight, minutes ago). The signal weight is the
    same `interactions.value` the long profile uses, so a like inside the session
    still says more than a dwell inside it.
    """
    combined: dict[str, float] = {}

    for terms, signal, minutes in vectors:
        share = signal * 0.5 ** (max(minutes, 0.0) / HALF_LIFE_MINUTES)
        if share <= 0:
            continue
        for term, frequency in terms.items():
            combined[term] = combined.get(term, 0.0) + frequency * share

    return combined


async def build(
    env, user_id: str, session_id: str | None, now: datetime
) -> tuple[dict[str, float], list[dict[str, float]]]:
    """The session vector and the clusters it was folded from.

    Both, because the weight is measured on how much those clusters resemble
    each other and the folded vector cannot answer that: three articles carry
    eighty terms whatever they are about.

    Recomputed per request rather than stored. It is a handful of rows, and
    recomputing is always right where a cache would have to be invalidated by
    the clock, which is the one thing a cache cannot watch.
    """
    if not session_id:
        return {}, []

    cutoff = now.timestamp() - WINDOW_MINUTES * 60
    rows = await query(
        env,
        "SELECT i.cluster_id, SUM(i.value) AS weight, MAX(i.created_at) AS last_at, "
        "t.term, t.tf "
        "FROM interactions i "
        "JOIN clusters c ON c.id = i.cluster_id "
        "JOIN article_terms t ON t.article_id = c.representative_article_id "
        "WHERE i.user_id = ? AND i.session_id = ? "
        "GROUP BY i.cluster_id, t.term",
        [user_id, session_id],
    )

    grouped: dict[int, tuple[dict[str, float], float, str]] = {}
    for row in rows:
        terms, _, _ = grouped.setdefault(
            row["cluster_id"], ({}, row["weight"] or 0.0, row["last_at"])
        )
        terms[row["term"]] = row["tf"]

    ready = []
    for terms, signal, last_at in grouped.values():
        if signal <= 0:
            continue
        seen = datetime.fromisoformat(last_at).timestamp()
        if seen < cutoff:
            continue
        ready.append((terms, signal, (now.timestamp() - seen) / 60.0))

    return decayed(ready), [terms for terms, _, _ in ready]


def leading(vector: dict[str, float], vectors: list[dict[str, float]]) -> str | None:
    """The subject the session is about, when it is about one.

    Named only when the weight is worth naming. Telling a reader they are on a
    run about something, while the ranking gave that run almost no say, would be
    describing a force that is not acting.
    """
    if not vector or weight(vectors) < MAX_WEIGHT / 2:
        return None

    return max(vector.items(), key=lambda item: (item[1], item[0]))[0]
