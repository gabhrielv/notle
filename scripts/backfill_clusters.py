"""Regroups the articles that were stored before clustering existed.

The corpus was built while every article opened its own cluster, so the window
the feed will read is entirely ungrouped. Left alone it would fix itself only as
the hourly runs replaced it, and until then the demo would show the repetition
this slice exists to remove.

This runs the same functions the ingestion does, over the corpus already in the
database, so it doubles as the first check of the real algorithm against real
headlines. It is idempotent: a second pass regroups to the same answer and every
statement becomes a no-op.

    uv run --group ingest python -m scripts.backfill_clusters --dry-run
    uv run --group ingest python -m scripts.backfill_clusters
"""

import argparse
from collections import defaultdict
from datetime import datetime

from ingest.clustering import assign_cluster, weigh
from ingest.pipeline import CLUSTER_WINDOW_HOURS, set_representatives
from ingest.store import MAX_BOUND_PARAMS, D1Client, chunked

PAGE = 2000


def read_articles(client: D1Client) -> list[dict]:
    """Oldest first, so the story that broke the news anchors its group."""
    return client.query(
        "SELECT id, cluster_id, published_at FROM articles ORDER BY published_at, id"
    )


def read_vectors(client: D1Client) -> dict[int, dict[str, float]]:
    """Every article's raw term frequencies, paged to keep responses small."""
    vectors: dict[int, dict[str, float]] = defaultdict(dict)
    offset = 0
    while True:
        rows = client.query(
            "SELECT article_id, term, tf FROM article_terms "
            "ORDER BY article_id, term LIMIT ? OFFSET ?",
            [PAGE, offset],
        )
        if not rows:
            return vectors

        for row in rows:
            vectors[row["article_id"]][row["term"]] = row["tf"]
        offset += PAGE


def read_corpus(client: D1Client) -> tuple[dict[str, int], int]:
    """The IDF inputs.

    Unlike an hourly run this reads the whole `terms` table, because a backfill
    touches every article and so needs every term anyway. It runs once.
    """
    rows = client.query("SELECT term, doc_count FROM terms")
    counts = {row["term"]: row["doc_count"] for row in rows}

    stats = client.query("SELECT total_docs FROM corpus_stats WHERE id = 1")
    return counts, (stats[0]["total_docs"] if stats else 0)


def regroup(articles, vectors, counts, total_docs) -> dict[int, int]:
    """Returns article id to the cluster id it belongs in.

    Anchors older than the window are dropped as the pass moves forward, which
    is what the ingestion gets for free from its `first_seen_at >= ?` filter.
    Without it a backfill over months of archive would compare every article
    against every cluster ever opened, and a story could attach to coverage from
    a different year.
    """
    window = CLUSTER_WINDOW_HOURS * 3600
    anchors: list[tuple[int, dict[str, float], str]] = []
    assignment: dict[int, int] = {}

    for article in articles:
        vector = vectors.get(article["id"])
        if not vector:
            assignment[article["id"]] = article["cluster_id"]
            continue

        published_at = article["published_at"]
        anchors = [a for a in anchors if _seconds_between(a[2], published_at) <= window]

        weighted = weigh(vector, counts, total_docs)
        cluster_id = assign_cluster(weighted, [(cid, vec) for cid, vec, _ in anchors])

        if cluster_id is None:
            # The article keeps the cluster it already had, and that cluster
            # becomes the anchor. Reusing the id rather than allocating a new
            # one means the only rows that change are the ones that move.
            cluster_id = article["cluster_id"]
            anchors.append((cluster_id, weighted, published_at))

        assignment[article["id"]] = cluster_id

    return assignment


def _seconds_between(earlier: str, later: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (datetime.strptime(later, fmt) - datetime.strptime(earlier, fmt)).total_seconds()


def _update_in_chunks(client: D1Client, sql: str, value, ids: list[int]) -> None:
    for chunk in chunked(ids, MAX_BOUND_PARAMS - 1):
        placeholders = ", ".join("?" * len(chunk))
        client.query(sql.format(placeholders=placeholders), [value, *chunk])


def apply(client: D1Client, articles, assignment: dict[int, int]) -> None:
    moved: dict[int, list[int]] = defaultdict(list)
    for article in articles:
        target = assignment[article["id"]]
        if target != article["cluster_id"]:
            moved[target].append(article["id"])

    for cluster_id, article_ids in moved.items():
        _update_in_chunks(
            client,
            "UPDATE articles SET cluster_id = ? WHERE id IN ({placeholders})",
            cluster_id,
            article_ids,
        )

    members: dict[int, list[dict]] = defaultdict(list)
    for article in articles:
        members[assignment[article["id"]]].append(article)

    set_representatives(
        client,
        {cluster_id: rows[0]["id"] for cluster_id, rows in members.items()},
    )

    by_size: dict[int, list[int]] = defaultdict(list)
    for cluster_id, rows in members.items():
        by_size[len(rows)].append(cluster_id)
    for size, cluster_ids in by_size.items():
        _update_in_chunks(
            client,
            "UPDATE clusters SET size = ? WHERE id IN ({placeholders})",
            size,
            cluster_ids,
        )

    emptied = [
        row["id"] for row in client.query("SELECT id FROM clusters") if row["id"] not in members
    ]
    for chunk in chunked(emptied, MAX_BOUND_PARAMS):
        placeholders = ", ".join("?" * len(chunk))
        client.query(f"DELETE FROM clusters WHERE id IN ({placeholders})", chunk)


def report(articles, assignment: dict[int, int]) -> None:
    members: dict[int, list[int]] = defaultdict(list)
    for article in articles:
        members[assignment[article["id"]]].append(article["id"])

    grouped = {cid: ids for cid, ids in members.items() if len(ids) > 1}
    print(f"{len(articles)} artigos")
    print(f"{len(members)} clusters, era {len({a['cluster_id'] for a in articles})}")
    print(f"{len(grouped)} com mais de um artigo, cobrindo {sum(len(i) for i in grouped.values())}")
    if grouped:
        print(f"maior: {max(len(i) for i in grouped.values())} artigos")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="calcula e mostra, sem escrever")
    args = parser.parse_args()

    client = D1Client.from_env()

    articles = read_articles(client)
    vectors = read_vectors(client)
    counts, total_docs = read_corpus(client)

    assignment = regroup(articles, vectors, counts, total_docs)
    report(articles, assignment)

    if args.dry_run:
        print("\ndry run, nada foi escrito")
        return

    apply(client, articles, assignment)
    print("\naplicado")


if __name__ == "__main__":
    main()
