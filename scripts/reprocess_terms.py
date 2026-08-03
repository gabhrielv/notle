"""Re-lemmatizes the corpus already stored, under today's rules.

`article_terms` holds whatever the normalizer decided when each article arrived,
so every word added to the discard lists since only changes articles that have
not been written yet. Three slices added words that way and none of them reached
the archive:

    `escolher`, which reached the strongest terms of a seeded profile and made
    the card say the reader follows "choosing".

    `favorite`, `acompanhar`, `perca`, `noticia`, the invitation verbs every
    portal ends a technology article with.

    The portals' own names, which entity recognition turns into terms because a
    portal names itself inside its own summaries.

Running this makes the stored corpus agree with the code that reads it. Until it
runs, the two disagree and the older an article is the more it disagrees, which
is a worse state than either rule on its own.

Not on a schedule. It re-runs spaCy over the whole archive and rewrites tens of
thousands of rows, which is minutes of work to fix something that only changes
when somebody edits a list. Triggered by hand, from the workflow of the same
name.

    uv run --group ingest python -m scripts.reprocess_terms --dry-run
    uv run --group ingest python -m scripts.reprocess_terms
"""

import argparse
from collections import Counter

from ingest.feeds import strip_promotion
from ingest.normalize import lemmatize, term_frequencies
from ingest.sources import portal_names
from ingest.store import MAX_BOUND_PARAMS, D1Client, chunked

# Articles per read. Summaries run to 600 characters, so a larger page is
# megabytes of response for no gain.
PAGE = 300


def read_articles(client: D1Client, offset: int) -> list[dict]:
    """Title, summary and the language its portal publishes in."""
    return client.query(
        "SELECT a.id, a.title, a.summary, s.feed_url "
        "FROM articles a JOIN sources s ON s.id = a.source_id "
        "ORDER BY a.id LIMIT ? OFFSET ?",
        [PAGE, offset],
    )


def languages() -> dict[str, str]:
    from ingest.sources import SOURCES

    return {source.feed_url: source.language for source in SOURCES}


def rewrite_summary(client: D1Client, article_id: int, summary: str) -> None:
    """Replaces a stored summary that still carries the portal's invitation.

    Three places hold it and all three have to move together. `articles.summary`
    is what the card shows the reader, `article_search` is a plain FTS5 table
    with its own copy rather than an external content one, and `article_terms`
    is rebuilt from the same text just below. Leaving the search index behind
    would make a query for the invitation return articles whose visible text no
    longer contains it.
    """
    client.query("UPDATE articles SET summary = ? WHERE id = ?", [summary, article_id])
    client.query(
        "UPDATE article_search SET summary = ? WHERE rowid = ?", [summary, article_id]
    )


def rewrite(client: D1Client, article_id: int, frequencies: dict[str, float]) -> None:
    """Replaces one article's terms.

    Delete then insert rather than reconcile. Which terms an article has is
    exactly what changed, so working out the difference costs a read to save
    writes that are already batched.
    """
    client.query("DELETE FROM article_terms WHERE article_id = ?", [article_id])
    client.insert_many(
        "article_terms",
        ("article_id", "term", "tf"),
        [(article_id, term, tf) for term, tf in frequencies.items()],
    )


def recount(client: D1Client, counts: Counter) -> None:
    """Rebuilds `terms.doc_count` from what the corpus now holds.

    Rewritten rather than adjusted. The counts drift with every article whose
    terms changed, and a delta would have to be computed per term against the
    old vector, which is the bookkeeping this job exists to avoid.
    """
    client.query("DELETE FROM terms")
    rows_per_request = MAX_BOUND_PARAMS // 2

    for chunk in chunked(list(counts.items()), rows_per_request):
        values = ", ".join(["(?, ?)"] * len(chunk))
        params = [value for pair in chunk for value in pair]
        client.query(f"INSERT INTO terms (term, doc_count) VALUES {values}", params)


def run(client: D1Client | None = None, dry_run: bool = False):
    client = client or D1Client.from_env()

    banned = portal_names()
    by_feed = languages()

    seen = 0
    changed = 0
    cleaned = 0
    counts: Counter = Counter()
    offset = 0

    while True:
        page = read_articles(client, offset)
        if not page:
            break

        for row in page:
            language = by_feed.get(row["feed_url"], "pt")

            # The stored summary predates the rule that strips the portal's
            # invitation, so it is fixed here before it is read for terms.
            summary = strip_promotion(row["summary"] or "")
            if summary != (row["summary"] or ""):
                cleaned += 1
                if not dry_run:
                    rewrite_summary(client, row["id"], summary)

            lemmas = lemmatize(f"{row['title']}. {summary}", language)
            frequencies = term_frequencies([x for x in lemmas if x not in banned])

            seen += 1
            if not frequencies:
                # An empty vector has cosine zero against every profile forever.
                # It was already dropped on the way in, so there is nothing here.
                continue

            counts.update(frequencies.keys())
            changed += 1
            if not dry_run:
                rewrite(client, row["id"], frequencies)

        offset += PAGE

    if not dry_run:
        recount(client, counts)
        client.query("UPDATE corpus_stats SET total_docs = ? WHERE id = 1", [changed])

    return seen, changed, len(counts), cleaned


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    seen, changed, vocabulary, cleaned = run(dry_run=args.dry_run)
    verb = "reescreveria" if args.dry_run else "reescreveu"
    print(
        f"{seen} artigos lidos, {verb} {changed}, vocabulario de {vocabulary} termos, "
        f"{cleaned} resumos limpos de chamada promocional"
    )
