"""The screen a visitor sees before they have done anything.

Every visitor is anonymous, so every visitor is a cold start, and this is not an
edge case: it is the main path, and for most people the only screen they will
ever see. Until they answer it the feed has nothing to rank with and falls back
to the clock.

What it offers is chosen by the ingestion job and only read here. The twelve
headlines have to span the news rather than sample it, and working that out
means comparing candidates against each other, which is not something the
request that decides whether a visitor stays should be spending its budget on.

Two designs were rejected in the architecture and neither is reachable from
here. RSS categories are not comparable across portals, so the same subject
arrives as `economia`, `Economia`, `business`, `mercado` and blank. And a curated
list of seed terms rots, because the words that mean politics today are not the
ones that will in three months. Seeding from real headlines updates itself,
reuses clusters that already exist, and puts the visitor in front of the product
instead of in front of a form.
"""

from datetime import UTC, datetime

from api.db import execute, query
from api.feed import decorate

# How many of the twelve a visitor has to choose.
#
# Three is enough for a mean to point somewhere rather than at one story, and
# few enough that the screen is answered rather than filled in. The number is
# enforced as a maximum, not a minimum: someone who picks two has still said
# more than someone who skipped, and refusing that would trade a real signal for
# a tidy rule.
PICKS = 3


async def offer(env) -> list[dict]:
    """The headlines to show, in the order the job chose them."""
    rows = await query(
        env,
        "SELECT cluster_id FROM onboarding_picks ORDER BY position",
    )
    return await decorate(env, [{"cluster_id": row["cluster_id"]} for row in rows])


async def pending(env, user: dict) -> bool:
    """Whether this reader still owes the onboarding an answer."""
    return not user.get("onboarded_at")


def _valid(picks, offered: set[int]) -> list[int]:
    """The choices that are actually among what was offered.

    Filtered rather than trusted. `interactions.cluster_id` carries no foreign
    key, so an id that never existed would be stored happily and then poison the
    rebuild with a join that matches nothing. Checking against the offer rather
    than against `clusters` is the stronger test and costs the same, because it
    is the only set the screen could have produced.
    """
    if not isinstance(picks, list):
        return []

    seen: list[int] = []
    for pick in picks:
        if isinstance(pick, int) and pick in offered and pick not in seen:
            seen.append(pick)

    return seen[:PICKS]


async def answer(env, user_id: str, picks) -> list[int]:
    """Records the choices and marks the reader as having answered.

    The mark is written whether or not anything was chosen, which is what makes
    skipping work. Without it a visitor who skipped would meet the same form on
    every visit, and the way out of a screen that will not take no for an answer
    is the close button.
    """
    rows = await query(env, "SELECT cluster_id FROM onboarding_picks")
    chosen = _valid(picks, {row["cluster_id"] for row in rows})

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    if chosen:
        values = ", ".join(["(?, ?, 'seed', 1.0, ?)"] * len(chosen))
        params = [value for cluster_id in chosen for value in (user_id, cluster_id, stamp)]
        await execute(
            env,
            "INSERT INTO interactions (user_id, cluster_id, type, value, created_at) "
            f"VALUES {values}",
            params,
        )

    await execute(
        env,
        "UPDATE users SET onboarded_at = ? WHERE id = ?",
        [stamp, user_id],
    )

    return chosen
