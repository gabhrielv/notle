"""Decides which cluster an incoming article belongs to.

The `url UNIQUE` constraint only stops the same URL being read twice. The real
problem is that G1, BBC and CNN publish the same story under different URLs:

    "Copom mantem Selic em 10,5% ao ano"
    "Banco Central decide manter taxa Selic em 10,5%"
    "Selic: Copom mantem juros em 10,5%"

Ungrouped, those three take the top of the feed with tied scores, and liking one
pushes the other two up. Slice 2 solves it by comparing the incoming vector
against a 24 hour window. Slice 1 opens a cluster per article so that everything
downstream already speaks cluster, and slice 2 changes this function alone.
"""

from ingest.feeds import ArticleDraft


def assign_cluster(
    draft: ArticleDraft,
    vector: dict[str, float],
    recent_clusters: list[tuple[int, dict[str, float]]],
) -> int | None:
    """Returns the cluster to attach to, or None to open a new one.

    Slice 1 always returns None. `vector` and `recent_clusters` are already in
    the signature because slice 2 needs exactly them: the incoming article's
    weighted terms, and the clusters of the last 24 hours to compare against.
    """
    return None
