"""Reaches from what a reader touched to the subjects next to it.

The architecture's answer to the absorbing state. Every other mechanism here
reinforces: the long profile strengthens what was touched, the session
strengthens what was just touched, the negative vector only removes, and the
decay only knows about age. None introduces anything genuinely new, and the
consequence is arithmetic rather than philosophical: a subject never touched has
a cosine near zero, so it never rises, so it is never shown, so it can never be
liked, so it never enters the profile.

That has a name in the literature. Zemblanity, Boyd's opposite of serendipity,
which Santini gives as "predictable and worthless encounters, arising from a
model". A recommender that converges without a counterweight is a machine for
producing them.

This is one of two counterweights, and the quieter one. It does not introduce a
subject from nowhere; it follows an edge the corpus itself drew. If `selic`
appears beside `cambio` across the archive, a reader who follows one is offered
the other, and the card can say why in a sentence somebody would accept: people
who follow Selic tend to follow the exchange rate.

**It is not collaborative filtering and this module does not call it that.** No
other reader is consulted, and none needs to exist.
"""

from api.db import MAX_BOUND_PARAMS, query

# How many of the reader's own terms get expanded.
#
# The strongest few, not the whole profile. Expanding a long tail would pull in
# the neighbours of terms the reader barely touched, and those neighbours arrive
# with the same standing as the ones that matter.
SEEDS = 12

# How far a neighbour's weight falls below the term that reached it.
#
# The expanded vector has to stay an offer rather than a claim. At 0.5 a
# neighbour starts at half of what the reader actually showed interest in, and
# is then multiplied by the co-occurrence score, which is itself under one. So a
# strong neighbour of a strong term arrives at roughly a quarter of that term's
# weight, and nothing the reader never touched can outweigh something they did.
REACH = 0.5


async def neighbours(env, terms: list[str]) -> dict[str, list[tuple[str, float]]]:
    """The stored neighbours of each term, read in bounded chunks."""
    if not terms:
        return {}

    found: dict[str, list[tuple[str, float]]] = {}
    for start in range(0, len(terms), MAX_BOUND_PARAMS):
        chunk = terms[start : start + MAX_BOUND_PARAMS]
        placeholders = ", ".join("?" * len(chunk))
        rows = await query(
            env,
            "SELECT term_a, term_b, score FROM term_cooccur "
            f"WHERE term_a IN ({placeholders})",
            chunk,
        )
        for row in rows:
            found.setdefault(row["term_a"], []).append((row["term_b"], row["score"]))

    return found


def expanded(profile: dict[str, float], edges: dict[str, list[tuple[str, float]]]):
    """The neighbouring subjects, without the ones the reader already has.

    Terms already in the profile are dropped rather than added to. Keeping them
    would make this a louder copy of the long profile, and every extra point of
    agreement with what the reader already reads is a point spent against the
    thing this exists to counteract.
    """
    reached: dict[str, float] = {}

    for term, weight in profile.items():
        for neighbour, score in edges.get(term, ()):
            if neighbour in profile:
                continue
            share = weight * score * REACH
            reached[neighbour] = max(reached.get(neighbour, 0.0), share)

    return reached


async def build(env, profile: dict[str, float], seeds: int = SEEDS) -> dict[str, float]:
    """One reader's adjacent subjects, or nothing if they have said nothing yet."""
    if not profile:
        return {}

    strongest = sorted(profile.items(), key=lambda item: (-item[1], item[0]))[:seeds]
    edges = await neighbours(env, [term for term, _ in strongest])

    return expanded(dict(strongest), edges)
