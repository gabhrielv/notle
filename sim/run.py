"""Runs a persona against the ranking and reports what it learned.

The scoring here is the Worker's own. `ranking.score` and `ranking.vectors` are
imported rather than reimplemented, and the profile is folded exactly the way
`api.profile.combine` folds it, because a simulator that approximates the formula
calibrates the approximation.

What is reimplemented is only the part that is SQL in production: the dot product
across the inverted index, which here is a loop over an in-memory corpus. The
arithmetic on either side of it is shared.
"""

from dataclasses import dataclass, replace

from ranking import score as scoring
from ranking.vectors import cosine, norm, weigh
from sim.personas import Persona, answer

# How many cards a simulated page holds, matching the real feed.
PAGE = 24


@dataclass(frozen=True)
class Constants:
    """The five the grid moves. Defaults are whatever the code ships with."""

    w_recencia: float = scoring.W_RECENCIA
    beta: float = scoring.BETA
    w_coocor: float = scoring.W_COOCOR
    session_cap: float = 0.35
    half_life: float = scoring.HALF_LIFE_HOURS

    def decay(self, age_hours: float) -> float:
        return 0.5 ** (max(age_hours, 0.0) / self.half_life)


@dataclass
class Reader:
    """One simulated visitor's accumulated state."""

    kept: list[int]
    hidden: list[int]

    @classmethod
    def new(cls):
        return cls(kept=[], hidden=[])

    def answered(self) -> set[int]:
        return set(self.kept) | set(self.hidden)


def profile_of(clusters: list[int], snapshot) -> dict[str, float]:
    """The mean of the chosen clusters' vectors, as `api.profile.combine` folds it."""
    if not clusters:
        return {}

    combined: dict[str, float] = {}
    share = 1.0 / len(clusters)
    for cluster_id in clusters:
        for term, frequency in snapshot.vectors.get(cluster_id, {}).items():
            combined[term] = combined.get(term, 0.0) + frequency * share

    return combined


def expand(profile: dict[str, float], snapshot, seeds: int = 12) -> dict[str, float]:
    """The adjacent subjects, as `api.expand` builds them."""
    if not profile:
        return {}

    strongest = sorted(profile.items(), key=lambda item: (-item[1], item[0]))[:seeds]
    chosen = dict(strongest)

    reached: dict[str, float] = {}
    for term, weight in chosen.items():
        for neighbour, edge in snapshot.edges.get(term, ()):
            if neighbour in chosen:
                continue
            reached[neighbour] = max(reached.get(neighbour, 0.0), weight * edge * 0.5)

    return reached


def rank(reader: Reader, snapshot, constants: Constants, now_hours: float) -> list[dict]:
    """One page, scored the way the Worker scores it."""
    kept = weigh(profile_of(reader.kept, snapshot), snapshot.document_counts, snapshot.total_docs)
    avoided = weigh(
        profile_of(reader.hidden, snapshot), snapshot.document_counts, snapshot.total_docs
    )
    nearby = weigh(
        expand(profile_of(reader.kept, snapshot), snapshot),
        snapshot.document_counts,
        snapshot.total_docs,
    )

    answered = reader.answered()
    scored = []

    for cluster_id, raw in snapshot.vectors.items():
        if cluster_id in answered:
            continue

        card = snapshot.cards.get(cluster_id)
        if card is None:
            continue

        item = weigh(raw, snapshot.document_counts, snapshot.total_docs)
        if not norm(item):
            continue

        affinity = cosine(kept, item)
        penalty = scoring.rejection(cosine(avoided, item))
        adjacent = cosine(nearby, item)
        age = max(now_hours - _age(card["published_at"]), 0.0)

        value = (
            scoring.W_GOSTO * affinity + constants.w_coocor * adjacent + constants.w_recencia
        ) * constants.decay(age) - constants.beta * penalty

        scored.append({**card, "cluster_id": cluster_id, "score": value})

    scored.sort(key=lambda card: -card["score"])
    return scored[:PAGE]


_EPOCH: dict[str, float] = {}


def _age(published_at: str) -> float:
    """Publication time in hours since the oldest story in the corpus.

    Relative rather than absolute, so a simulation gives the same answer next
    week as it does today. The decay only ever sees differences.
    """
    from datetime import datetime

    if published_at not in _EPOCH:
        _EPOCH[published_at] = datetime.fromisoformat(published_at).timestamp() / 3600.0
    return _EPOCH[published_at]


def precision(page: list[dict], persona: Persona) -> float:
    """How much of the page is on the persona's actual subject."""
    if not page:
        return 0.0
    return sum(1 for card in page if persona.likes(card)) / len(page)


def diversity(page: list[dict]) -> float:
    """Distinct portals in the page, over the page length.

    The brake on the other metric. Precision alone is maximised by a feed that
    has collapsed into one subject, which is exactly the zemblanity the
    discovery slots exist to prevent, so a constant that buys precision by
    collapsing the feed has to be visible as such.
    """
    if not page:
        return 0.0
    return len({card["source"] for card in page}) / len(page)


def simulate(persona: Persona, snapshot, constants: Constants, rounds: int = 8):
    """One reader, `rounds` pages, reporting what each page looked like."""
    newest = max(_age(card["published_at"]) for card in snapshot.cards.values())
    reader = Reader.new()
    history = []

    for _ in range(rounds):
        page = rank(reader, snapshot, constants, newest)
        history.append(
            {
                "precision": precision(page, persona),
                "diversity": diversity(page),
                "size": len(page),
            }
        )

        keeps, hides = answer(persona, page)
        reader.kept.extend(keeps)
        reader.hidden.extend(hides)

    return history


def baseline(persona: Persona, snapshot) -> float:
    """The share of the whole window that is on the persona's subject.

    What precision would be with no ranking at all, which is the number every
    result has to be read against.
    """
    cards = list(snapshot.cards.values())
    if not cards:
        return 0.0
    return sum(1 for card in cards if persona.likes(card)) / len(cards)


def sweep(persona: Persona, snapshot, field: str, values, rounds: int = 8):
    """One constant, several values, everything else where the code left it.

    Scored on the best round rather than the last, and that is a finding rather
    than a convenience. Precision rises for about five rounds and then collapses,
    because the mean profile is captured by whatever vocabulary repeats across
    what was kept, and across a heterogeneous set that is the filler rather than
    the subject. Reading the last round would rank constants by how fast they
    reach that collapse.

    Five rounds is also the honest horizon for this product. A visitor to a demo
    gives a handful of answers, not forty.
    """
    results = []
    for value in values:
        constants = replace(Constants(), **{field: value})
        history = simulate(persona, snapshot, constants, rounds)
        best = max(history, key=lambda step: step["precision"])
        results.append(
            {
                "value": value,
                "precision": best["precision"],
                "diversity": best["diversity"],
                "peak_round": history.index(best) + 1,
                "curve": [round(step["precision"], 3) for step in history],
            }
        )
    return results
