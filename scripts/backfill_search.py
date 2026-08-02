"""Indexes the articles that were stored before search existed.

The corpus was built for a feed, not for a search box, so `article_search`
starts empty while `articles` already holds thousands of rows. Left alone it
would fill only as the hourly runs added new stories, and a search over the last
hour is not a search.

The whole backfill is one statement. Both tables live in the same database, so
reading thousands of titles out over HTTP only to write them back would be a
round trip that buys nothing. `INSERT OR IGNORE` keyed on the article id makes
it idempotent: a second pass writes nothing, and a run that failed can just be
repeated.

    uv run --group ingest python -m scripts.backfill_search --dry-run
    uv run --group ingest python -m scripts.backfill_search

Without credentials to hand it is the same one statement through wrangler:

    npx wrangler d1 execute notle --remote --command \\
      "INSERT OR IGNORE INTO article_search(rowid, title, summary) \\
       SELECT id, title, summary FROM articles"
"""

import argparse

from ingest.store import D1Client

FILL = (
    "INSERT OR IGNORE INTO article_search(rowid, title, summary) "
    "SELECT id, title, summary FROM articles"
)


def indexed(client: D1Client) -> int:
    rows = client.query("SELECT COUNT(*) AS n FROM article_search")
    return rows[0]["n"] if rows else 0


def pending(client: D1Client) -> int:
    """Articles the search index does not hold yet."""
    rows = client.query(
        "SELECT COUNT(*) AS n FROM articles a "
        "WHERE NOT EXISTS (SELECT 1 FROM article_search s WHERE s.rowid = a.id)"
    )
    return rows[0]["n"] if rows else 0


def run(client: D1Client | None = None, dry_run: bool = False) -> int:
    client = client or D1Client.from_env()

    missing = pending(client)
    if not dry_run and missing:
        client.query(FILL)

    return missing


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = D1Client.from_env()
    missing = run(client, dry_run=args.dry_run)

    verb = "indexaria" if args.dry_run else "indexou"
    print(f"{verb} {missing} artigos, indice agora com {indexed(client)}")
