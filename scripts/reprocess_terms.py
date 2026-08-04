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

It is also the only job that reads the whole archive, which makes it the only
place the canonical map can be counted. A written word's term is decided by how
that word was read where its capital carried information, and that is a tally
over every occurrence in the corpus rather than anything one article can settle.
The map is written to `term_canonical` for the hourly ingestion to apply, so the
corpus stops splitting the moment this finishes instead of drifting back a few
thousand articles at a time until somebody runs it again.

Two passes over the articles, one over spaCy. The vote has to be complete before
any article can be canonized, and re-running the model to get there would double
the expensive half of the job, so the readings are held in memory between the
passes.

Not on a schedule. It rewrites tens of thousands of rows to fix something that
only changes when somebody edits a list. Triggered by hand, from the workflow of
the same name.

    uv run --group ingest python -m scripts.reprocess_terms --dry-run
    uv run --group ingest python -m scripts.reprocess_terms
"""

import argparse
from collections import Counter

from ingest.feeds import strip_promotion
from ingest.normalize import (
    SurfaceVotes,
    canonical_map,
    canonize,
    occurrences,
    tally,
    term_frequencies,
)
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


def read_all(client: D1Client):
    """Every article, a page at a time."""
    offset = 0
    while True:
        page = read_articles(client, offset)
        if not page:
            return
        yield from page
        offset += PAGE


def languages() -> dict[str, str]:
    from ingest.sources import SOURCES

    return {source.feed_url: source.language for source in SOURCES}


def rewrite_text(client: D1Client, article_id: int, title: str, summary: str) -> None:
    """Replaces stored text that still carries the portal's invitation.

    Four places hold it and all four have to move together. `articles` is what
    the card shows the reader, `article_search` is a plain FTS5 table with its
    own copy rather than an external content one, and `article_terms` is rebuilt
    from the same text below. Leaving the search index behind would make a query
    for the invitation return articles whose visible text no longer contains it.

    The title is cleaned here and not only the summary. Arriving articles have
    had both cleaned since the rule existed, because `clean_summary` runs over
    the title too, but this job only ever rewrote the summary and then
    lemmatized the stored title raw. So the one place carrying the invitation
    into today's corpus was the half of the text this job read without fixing.
    """
    client.query(
        "UPDATE articles SET title = ?, summary = ? WHERE id = ?",
        [title, summary, article_id],
    )
    client.query(
        "UPDATE article_search SET title = ?, summary = ? WHERE rowid = ?",
        [title, summary, article_id],
    )


def rewrite_canonical(client: D1Client, canonical: dict[str, str]) -> None:
    """Replaces the canonical map with what this pass counted.

    Rewritten whole rather than merged. The vote is over the corpus as it stands
    now, so a surface that lost its evidence since the last run should lose its
    entry, and reconciling that costs a read to save writes that are batched.
    """
    client.query("DELETE FROM term_canonical")
    client.insert_many(
        "term_canonical",
        ("surface", "canonical"),
        sorted(canonical.items()),
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

    votes: dict[str, SurfaceVotes] = {}
    readings: list[tuple[int, list]] = []
    cleaned = 0

    # First pass: read every article, fix the text the invitation rule reached
    # after it was stored, and poll how each written word was read.
    for row in read_all(client):
        language = by_feed.get(row["feed_url"], "pt")

        title = strip_promotion(row["title"] or "")
        summary = strip_promotion(row["summary"] or "")
        if (title, summary) != ((row["title"] or ""), (row["summary"] or "")):
            cleaned += 1
            if not dry_run:
                rewrite_text(client, row["id"], title, summary)

        found = occurrences(f"{title}. {summary}", language)
        tally(votes, found)
        readings.append((row["id"], found))

    canonical = canonical_map(votes)

    seen = 0
    changed = 0
    counts: Counter = Counter()

    # Second pass: no model runs here. The vote is complete, so each article's
    # readings can be held to it and written.
    for article_id, found in readings:
        lemmas = canonize(found, canonical)
        frequencies = term_frequencies([x for x in lemmas if x not in banned])

        seen += 1
        if not frequencies:
            # An empty vector has cosine zero against every profile forever.
            # It was already dropped on the way in, so there is nothing here.
            continue

        counts.update(frequencies.keys())
        changed += 1
        if not dry_run:
            rewrite(client, article_id, frequencies)

    if not dry_run:
        rewrite_canonical(client, canonical)
        recount(client, counts)
        client.query("UPDATE corpus_stats SET total_docs = ? WHERE id = 1", [changed])

    return seen, changed, len(counts), cleaned, len(canonical)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    seen, changed, vocabulary, cleaned, canonized = run(dry_run=args.dry_run)
    verb = "reescreveria" if args.dry_run else "reescreveu"
    print(
        f"{seen} artigos lidos, {verb} {changed}, vocabulario de {vocabulary} termos, "
        f"{cleaned} textos limpos de chamada promocional, "
        f"{canonized} palavras escritas com forma canonica"
    )
