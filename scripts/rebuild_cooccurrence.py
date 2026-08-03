"""Rebuilds `term_cooccur` from the whole corpus.

Its own entry point and its own schedule, separate from the hourly ingestion.
Co-occurrence over the full archive is a different shape of job: it reads
everything rather than the last hour, it is quadratic in what each article
contributes, and the answer moves slowly enough that a week between runs costs
nothing anybody could notice.

    uv run --group ingest python -m scripts.rebuild_cooccurrence --dry-run
    uv run --group ingest python -m scripts.rebuild_cooccurrence
"""

import argparse
from collections import defaultdict

from ingest import cooccurrence
from ingest.store import D1Client

# Rows per read. Article terms run to nearly ninety thousand, and a page this
# size keeps each response small enough to parse without holding two copies of
# the corpus in memory at once.
PAGE = 5000


def read_terms(client: D1Client) -> dict[int, set[str]]:
    """Every article's terms, as a set per article."""
    articles: dict[int, set[str]] = defaultdict(set)

    offset = 0
    while True:
        rows = client.query(
            "SELECT article_id, term FROM article_terms ORDER BY article_id LIMIT ? OFFSET ?",
            [PAGE, offset],
        )
        if not rows:
            break
        for row in rows:
            articles[row["article_id"]].add(row["term"])
        offset += PAGE

    return articles


def read_document_counts(client: D1Client) -> dict[str, int]:
    """Only the terms that could be eligible, so the read follows the answer."""
    counts: dict[str, int] = {}

    offset = 0
    while True:
        rows = client.query(
            "SELECT term, doc_count FROM terms WHERE doc_count >= ? "
            "ORDER BY term LIMIT ? OFFSET ?",
            [cooccurrence.MIN_DOC_COUNT, PAGE, offset],
        )
        if not rows:
            break
        counts.update({row["term"]: row["doc_count"] for row in rows})
        offset += PAGE

    return counts


def read_source_spread(client: D1Client) -> dict[str, int]:
    """How many distinct portals used each eligible term.

    One row per term rather than per occurrence, so this stays small next to the
    corpus it summarises.
    """
    spread: dict[str, int] = {}

    offset = 0
    while True:
        rows = client.query(
            "SELECT t.term AS term, COUNT(DISTINCT a.source_id) AS sources "
            "FROM article_terms t JOIN articles a ON a.id = t.article_id "
            "WHERE t.term IN (SELECT term FROM terms WHERE doc_count >= ?) "
            "GROUP BY t.term ORDER BY t.term LIMIT ? OFFSET ?",
            [cooccurrence.MIN_DOC_COUNT, PAGE, offset],
        )
        if not rows:
            break
        spread.update({row["term"]: row["sources"] for row in rows})
        offset += PAGE

    return spread


def materialize(client: D1Client, rows) -> None:
    """Replaces the table wholesale.

    Rewritten rather than reconciled, like every other derived table here. The
    scores shift as the corpus grows, so most of what changes on a weekly run is
    the numbers rather than which pairs exist, and reconciling would cost a read
    per row to save writes that are cheap.
    """
    client.query("DELETE FROM term_cooccur")
    client.insert_many("term_cooccur", ("term_a", "term_b", "score"), rows)


def run(client: D1Client | None = None, dry_run: bool = False):
    client = client or D1Client.from_env()

    counts = read_document_counts(client)
    eligible = cooccurrence.eligible_terms(counts, read_source_spread(client))
    articles = read_terms(client)

    pairs = cooccurrence.count_pairs(articles, eligible)
    rows = cooccurrence.strongest_neighbours(pairs, counts)

    if not dry_run:
        materialize(client, rows)

    return len(articles), len(eligible), len(pairs), len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    articles, eligible, pairs, rows = run(dry_run=args.dry_run)
    verb = "escreveria" if args.dry_run else "escreveu"
    print(
        f"{articles} artigos, {eligible} termos elegiveis, "
        f"{pairs} pares distintos, {verb} {rows} vizinhos"
    )
