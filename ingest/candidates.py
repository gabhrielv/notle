"""Materializes the clusters a feed request is allowed to consider.

The corpus only changes when this job runs, so nothing a request could compute
from it would be fresher than what the job can leave behind. Precomputing is not
a cache that risks being wrong here; it is moving work to the side of the line
where time is free.

What moves is the IDF. Weighting a cluster's terms and taking the length of the
result is a pass over every term of every candidate, and doing it per request
would mean reading the whole window back into the Worker just to divide by a
number. Written here, the request sends its profile terms, the database sums the
products across the inverted index, and the division is one multiplication
against a column that was already there.

The consequence is that `norm` is measured under the IDF of the moment it was
written rather than of the moment it is used. Between two hourly runs the corpus
does not move, so within a run the ruler is consistent, which is the property
that matters: every candidate in a given feed was measured the same way.
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta

from ranking.score import age_in_hours, decay
from ranking.vectors import norm, strongest, weigh

# How far back the feed is allowed to look. At a 12 hour half life a story from
# the far edge of this window carries 6% of the weight of one from now, so
# reaching further would only add rows that can never place.
FEED_WINDOW_HOURS = 48

# How many terms of a cluster are kept for the screen. Enough to explain a
# position, short enough that the column stays small on every row.
TOP_TERMS = 6


def read_window(client, now: datetime) -> list[dict]:
    """The anchor of every cluster young enough to appear, with its terms.

    Reading the anchor rather than every member is the same choice clustering
    made: the members are near duplicates by construction, so their extra
    vocabulary is marginal, and one article per cluster keeps this proportional
    to the window instead of to how heavily an event was covered.
    """
    since = (now - timedelta(hours=FEED_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return client.query(
        "SELECT c.id AS cluster_id, a.published_at, t.term, t.tf "
        "FROM clusters c "
        "JOIN articles a ON a.id = c.representative_article_id "
        "JOIN article_terms t ON t.article_id = a.id "
        "WHERE c.first_seen_at >= ?",
        [since],
    )


def build(rows: list[dict], document_counts: dict[str, int], total_docs: int, now: datetime):
    """Turns the window into the rows `feed_candidates` should hold.

    A cluster whose weighted vector has no length is dropped rather than stored.
    It would divide to an affinity of zero against every profile forever, so the
    row could only ever cost a scan.
    """
    frequencies: dict[int, dict[str, float]] = defaultdict(dict)
    published: dict[int, str] = {}
    for row in rows:
        frequencies[row["cluster_id"]][row["term"]] = row["tf"]
        published[row["cluster_id"]] = row["published_at"]

    candidates = []
    for cluster_id, terms in frequencies.items():
        weighted = weigh(terms, document_counts, total_docs)
        length = norm(weighted)
        if not length:
            continue

        published_at = published[cluster_id]
        candidates.append(
            (
                cluster_id,
                decay(age_in_hours(published_at, now)),
                length,
                published_at,
                json.dumps(strongest(weighted, TOP_TERMS), ensure_ascii=False),
            )
        )

    return candidates


def materialize(client, candidates) -> None:
    """Replaces the table with this run's window.

    Rewriting rather than reconciling: the window slides every hour, so most of
    what changes is which rows belong at all, and working that out costs more
    than writing a few hundred rows. `feed_candidates` is derived from tables
    that survive, so losing it between the delete and the insert costs an empty
    feed for the length of one job, not data.
    """
    client.query("DELETE FROM feed_candidates")
    client.insert_many(
        "feed_candidates",
        ("cluster_id", "base_score", "norm", "published_at", "top_terms"),
        candidates,
    )
