"""Chooses the headlines the onboarding offers a visitor who has done nothing.

Every visitor is anonymous, so every visitor is a cold start, and this is the
only screen most of them will ever see. What it shows has to span the news
rather than sample it: a seed vector built from three stories about the same
thing is a narrower profile than no profile at all.

Recency alone does not do that, and the failure is not subtle. Against the live
window of 1332 clusters, the twelve freshest were eight G1 items and read as a
police blotter: a man electrocuted cutting grass, a body found on a dirt road, a
woman arrested with crack in a toilet, a pile up on a motorway. A visitor shown
that learns the product is about accidents in the interior of Sao Paulo.

Three things fix it, and each was measured against that window.
"""

import math
from datetime import datetime, timedelta

from ranking.score import decay
from ranking.vectors import cosine, norm, weigh

# How many headlines the screen offers.
#
# Twelve fits three or four to a row without scrolling on a phone, and it is
# enough for a reader to find three they care about. More turns a first
# impression into a form; fewer risks a visitor who recognises nothing.
OFFER = 12

# How far back the onboarding looks.
#
# Shorter than the feed's own 48 hours on purpose. This screen is a sample of
# what the product is like right now, and a story from the day before yesterday
# answers that worse than one from this morning, however good it was.
WINDOW_HOURS = 24

# How much a story being carried by several portals is worth.
#
# The first and largest fix. Freshness cannot separate a window where everything
# arrived within the hour: `decay` is between 0.95 and 1.0 across all of it, so a
# spread of 0.05 decides twelve slots out of 1332 candidates. Coverage is the
# corpus's own answer to which of those was the day's news, and it separates
# properly: 1223 clusters were carried by one portal, 83 by two, 21 by three, 5
# by four or more.
#
# Counted in distinct portals rather than in articles, and that distinction is
# the whole of it. By article count the top of the screen came back as "Previsao
# do tempo hoje para Cabo de Santo Agostinho", which holds 21 articles, and
# "Quina hoje: resultado do concurso 7081", which holds 10. Neither is the day's
# news; both are one portal republishing a template per city and per draw.
# Distinct portals scores those at one and they disappear, while a story two
# portals both thought worth running keeps its bonus.
COVERAGE = 1.0

# How much resembling an already chosen story costs a candidate.
#
# At 1.0 the penalty is on the same scale as the score it is subtracted from, so
# a near duplicate of something already on the screen is out regardless of how
# fresh it is, and a story about something else pays nothing.
#
# This is a different constant from the ranking's BETA even though both weigh a
# cosine against a score. That one is about what a reader rejected; this one is
# about what is already on the screen, and nobody has expressed anything.
VARIETY = 1.0

# How many of the twelve one portal may hold.
#
# G1 publishes 678 of the 1332 clusters in the window, more than the other five
# together, so without a ceiling it takes half the screen on volume alone. That
# is a fact about publishing rates, not about what a visitor should be shown
# first.
PER_SOURCE = 3


def read_window(client, now: datetime) -> list[dict]:
    """The anchor terms of every cluster young enough to be offered."""
    since = (now - timedelta(hours=WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return client.query(
        "SELECT c.id AS cluster_id, a.published_at, t.term, t.tf "
        "FROM clusters c "
        "JOIN articles a ON a.id = c.representative_article_id "
        "JOIN article_terms t ON t.article_id = a.id "
        "WHERE c.first_seen_at >= ?",
        [since],
    )


def read_coverage(client, now: datetime) -> dict[int, tuple[int, int]]:
    """How many portals carried each cluster, and which one wrote its anchor.

    One row per cluster rather than per term, so this stays small next to the
    window itself.
    """
    since = (now - timedelta(hours=WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = client.query(
        "SELECT c.id AS cluster_id, anchor.source_id AS source_id, "
        "COUNT(DISTINCT member.source_id) AS portals "
        "FROM clusters c "
        "JOIN articles anchor ON anchor.id = c.representative_article_id "
        "JOIN articles member ON member.cluster_id = c.id "
        "WHERE c.first_seen_at >= ? "
        "GROUP BY c.id",
        [since],
    )
    return {row["cluster_id"]: (row["portals"], row["source_id"]) for row in rows}


def assemble(rows, coverage, document_counts, total_docs, now: datetime):
    """Groups the rows into scored, weighted cluster vectors.

    The score is freshness lifted by how many portals carried the story. A
    cluster with no coverage row is one the query above did not see, so it is
    treated as carried by one portal rather than dropped.
    """
    frequencies: dict[int, dict[str, float]] = {}
    published: dict[int, str] = {}

    for row in rows:
        frequencies.setdefault(row["cluster_id"], {})[row["term"]] = row["tf"]
        published[row["cluster_id"]] = row["published_at"]

    candidates = []
    for cluster_id, terms in frequencies.items():
        weighted = weigh(terms, document_counts, total_docs)
        if not norm(weighted):
            # No length means no cosine against anything, ever. Offering it would
            # seed a profile that matches nothing.
            continue

        portals, source_id = coverage.get(cluster_id, (1, None))
        age = (now - datetime.fromisoformat(published[cluster_id])).total_seconds() / 3600.0
        score = decay(age) * (1 + COVERAGE * math.log(portals))

        candidates.append((cluster_id, weighted, score, source_id))

    return candidates


def choose(candidates, offer: int = OFFER) -> list[int]:
    """Picks a spread of stories rather than the freshest ones.

    Greedy and marginal: take the strongest, then each time the one whose score,
    minus how much it resembles anything already chosen, is highest. Nobody gets
    a slot once their portal holds `PER_SOURCE` of them.

    Deterministic, ties breaking on the cluster id, so two runs over one window
    choose the same twelve. A screen that reshuffles on reload would look random,
    which is the opposite of what this is.
    """
    remaining = list(candidates)
    chosen: list[int] = []
    taken: list[dict[str, float]] = []
    held: dict[int, int] = {}

    while remaining and len(chosen) < offer:
        best = None
        best_value = None

        for entry in remaining:
            cluster_id, vector, score, source_id = entry
            if held.get(source_id, 0) >= PER_SOURCE:
                continue

            resemblance = max((cosine(vector, other) for other in taken), default=0.0)
            value = (score - VARIETY * resemblance, -cluster_id)

            if best_value is None or value > best_value:
                best = entry
                best_value = value

        if best is None:
            # Every portal still holding a candidate has filled its quota. A
            # shorter screen is the honest outcome; relaxing the ceiling here
            # would make it a suggestion rather than a rule.
            break

        cluster_id, vector, _, source_id = best
        chosen.append(cluster_id)
        taken.append(vector)
        held[source_id] = held.get(source_id, 0) + 1
        remaining.remove(best)

    return chosen


def materialize(client, chosen: list[int]) -> None:
    """Replaces the offer with this run's.

    Rewritten rather than reconciled, like `feed_candidates`: the window slides
    every hour and most of what changes is which rows belong at all. Losing the
    table between the delete and the insert costs one job's worth of onboarding,
    not data, because it is derived from tables that survive.
    """
    client.query("DELETE FROM onboarding_picks")
    client.insert_many(
        "onboarding_picks",
        ("cluster_id", "position"),
        [(cluster_id, position) for position, cluster_id in enumerate(chosen)],
    )
