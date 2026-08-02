"""The two ways of reading the corpus that ignore taste.

The feed answers "what should I read", which is a question about one reader. These
answer "what happened" and "where is the story about X", which are questions about
the corpus and have the same answer for everybody. Nothing here touches a profile,
weighs a vector or applies a decay: one is ordered by the clock, the other by how
well the text matches what was typed.

That is also why neither records anything. Only `POST /api/interactions` writes,
so a reader browsing or searching leaves the profile exactly as they found it,
whether or not they asked for it.
"""

import re

from api.db import query
from api.feed import decorate

# Rows per request, for both lists. The feed's own page is 24; these are longer
# because they are scrolled rather than read, and each extra row costs one more
# row in the two detail queries `decorate` already issues.
PAGE = 30

# How many hidden clusters can be excluded inside the statement. D1 binds at
# most 100 parameters, and the page needs three of them. A reader who has hidden
# more than this many separate stories on a public demo does not exist yet, and
# if they ever do the tail of their hides simply stops being filtered rather
# than the request failing.
MAX_EXCLUSIONS = 90

# Letters, digits and nothing else, which under Python's Unicode rules keeps
# accented words whole. Taking the words this way rather than stripping a list
# of FTS5 operators is what makes the result predictable: whatever arrives, each
# token is one word, so quoting it cannot produce an expression.
_WORDS = re.compile(r"\w+", re.UNICODE)


def match_expression(raw: str) -> str:
    """Turns typed text into an FTS5 MATCH string, or an empty one.

    A search box takes text, not an expression. `Selic?` has to find what `Selic`
    finds, and a stray quote must not become a syntax error the reader is left to
    diagnose, so the operators never survive to reach FTS5 at all.

    Each word is quoted and the words are joined by a space, which FTS5 reads as
    AND: every word has to appear somewhere in the title or the summary. OR would
    return a page of stories matching only the most common word typed, which
    reads as the search being broken.
    """
    return " ".join(f'"{word}"' for word in _WORDS.findall(raw))


def _exclusion(hidden: set[int]) -> tuple[str, list[int]]:
    """The clause and parameters that keep hidden clusters out, if there are any."""
    if not hidden:
        return "", []

    capped = sorted(hidden)[:MAX_EXCLUSIONS]
    placeholders = ", ".join("?" * len(capped))
    return f"AND c.id NOT IN ({placeholders}) ", capped


async def latest(env, offset: int, hidden: set[int]) -> list[dict]:
    """Every cluster the corpus holds, newest first.

    Ordered on `clusters.first_seen_at`, which is the publication time of the
    article that opened the group, and which has an index. Not read from
    `feed_candidates`: that table is the 48 hour ranking window, and a list meant
    to be scrolled should keep going past where the feed stops caring.

    A cluster with no representative is one the ingestion opened and has not
    finished writing, so it has no headline to show yet.
    """
    clause, excluded = _exclusion(hidden)

    rows = await query(
        env,
        "SELECT c.id AS cluster_id FROM clusters c "
        "WHERE c.representative_article_id IS NOT NULL "
        f"{clause}"
        "ORDER BY c.first_seen_at DESC, c.id DESC LIMIT ? OFFSET ?",
        [*excluded, PAGE, offset],
    )

    return await decorate(env, [{"cluster_id": row["cluster_id"]} for row in rows])


async def search(env, raw: str, offset: int) -> list[dict]:
    """Clusters whose text matches what was typed, best match first.

    Grouped by cluster because the corpus stores one row per article and several
    portals cover one story. Without the grouping a search for a big event
    returns the same headline five times, which is the repetition clustering
    exists to remove, arriving through a different door.

    `bm25` returns lower numbers for better matches, so the strongest article in
    a group is its minimum, and that is what the group is ranked by.

    `AS MATERIALIZED` is load bearing rather than a hint about speed. An FTS5
    auxiliary function only works while the cursor that matched is still open,
    and grouping over a plain subquery lets SQLite flatten the two together,
    after which the same statement fails with "unable to use function bm25 in
    the requested context". Materializing the matches first keeps the function
    where it can answer and leaves the grouping to work on ordinary rows.

    Hidden clusters are not filtered out. Search is a question with a right
    answer, and refusing to return a story the reader asked for by name because
    they once hid something like it would make the box untrustworthy.
    """
    expression = match_expression(raw)
    if not expression:
        return []

    rows = await query(
        env,
        "WITH hits AS MATERIALIZED ("
        "  SELECT a.cluster_id AS cluster_id, bm25(article_search) AS rank"
        "  FROM article_search"
        "  JOIN articles a ON a.id = article_search.rowid"
        "  WHERE article_search MATCH ?"
        ") "
        "SELECT cluster_id, MIN(rank) AS rank FROM hits "
        "WHERE cluster_id IS NOT NULL "
        "GROUP BY cluster_id ORDER BY rank LIMIT ? OFFSET ?",
        [expression, PAGE, offset],
    )

    return await decorate(env, [{"cluster_id": row["cluster_id"]} for row in rows])
