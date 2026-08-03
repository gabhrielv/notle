"""Removes the terms of articles nobody will compare against again.

The architecture promised this from the beginning and no code ever did it. Title
and summary are cheap; the volume is in `article_terms`, at about 28 rows per
article and 600 articles a day, which is six million rows a year.

The promise as written was to prune "beyond the ranking window", and that window
is 48 hours. Implemented literally it would break the profile. `signal_vectors`
builds a reader's taste by joining `article_terms` on the anchor of every cluster
they answered, so deleting terms older than two days would mean a like from
Tuesday silently losing its vector on Thursday, and a profile that shrinks on its
own with nothing to point at.

So two rules instead of one:

    Nothing an anchor of an answered cluster holds is ever removed.
    Everything else goes after RETENTION_DAYS.

The retention is not the ranking window either, and the reason is the weekly
co-occurrence job: it reads the whole archive, and its neighbour quality was
measured against 3121 articles. Cutting it to two days would leave it a tenth of
that and turn `selic` into a term with no neighbours.
"""

# How long an article's terms survive without anybody having answered for them.
#
# Three months rather than the 48 hour ranking window. Three things read this
# table and only one of them is the feed: clustering looks back a day,
# co-occurrence reads everything, and the profile reaches back as far as the
# reader's own history. The longest of those decides.
#
# It also sits past the long profile's own half life of sixty days, so a signal
# still worth more than a third of its original weight can never find its terms
# missing.
RETENTION_DAYS = 90


def plan(client, cutoff: str) -> int:
    """How many rows a prune would remove, without removing them."""
    rows = client.query(
        "SELECT COUNT(*) AS n FROM article_terms t "
        "WHERE t.article_id IN (SELECT id FROM articles WHERE published_at < ?) "
        "AND t.article_id NOT IN ("
        "  SELECT c.representative_article_id FROM clusters c "
        "  WHERE c.representative_article_id IS NOT NULL "
        "  AND c.id IN (SELECT DISTINCT cluster_id FROM interactions "
        "               WHERE cluster_id IS NOT NULL)"
        ")",
        [cutoff],
    )
    return rows[0]["n"] if rows else 0


def run(client, cutoff: str) -> int:
    """Removes them, and reports how many went.

    One statement. The subquery that protects answered clusters is evaluated by
    the database rather than assembled here, because the ids would otherwise
    have to be read out and bound back in under a hundred parameter ceiling, and
    a reader with a long history would silently stop being protected past the
    cap.
    """
    before = plan(client, cutoff)
    if not before:
        return 0

    client.query(
        "DELETE FROM article_terms "
        "WHERE article_id IN (SELECT id FROM articles WHERE published_at < ?) "
        "AND article_id NOT IN ("
        "  SELECT c.representative_article_id FROM clusters c "
        "  WHERE c.representative_article_id IS NOT NULL "
        "  AND c.id IN (SELECT DISTINCT cluster_id FROM interactions "
        "               WHERE cluster_id IS NOT NULL)"
        ")",
        [cutoff],
    )
    return before
