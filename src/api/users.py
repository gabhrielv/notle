"""Identifies a visitor without asking them for anything.

There is no login, no password and no secret, so the identifier is not a claim
about who someone is. It is a handle for the interactions they have already had
with this feed, and nothing hangs off it that would be worth stealing.

It travels in a cookie the Worker sets, rather than in something the page keeps
and sends. The first request has to be useful before any script has run, which
is the whole reason the feed is one call, and a value the browser attaches on its
own is the only way to know the visitor on that first request. HttpOnly on top,
because nothing on the page ever needs to read it and a script that could read
it could also carry it away.
"""

import uuid
from datetime import UTC, datetime

from api.db import execute, query_one

COOKIE = "nid"

# A year. Short enough that an abandoned profile does not live forever, long
# enough that coming back next week is still the same reader.
MAX_AGE = 60 * 60 * 24 * 365


def read_cookie(header: str | None) -> str | None:
    """Pulls our value out of a Cookie header, ignoring everything else in it."""
    if not header:
        return None

    for part in header.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name == COOKIE:
            return value.strip() or None

    return None


def set_cookie(user_id: str) -> str:
    """The Set-Cookie value for a visitor the Worker has just met.

    SameSite=Lax rather than Strict: the demo is a link people will follow from
    somewhere else, and Strict would hand them a brand new profile every time
    they arrived that way.
    """
    return f"{COOKIE}={user_id}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={MAX_AGE}"


def looks_like_ours(user_id: str | None) -> bool:
    """Cheap shape check before the value reaches a query.

    A cookie is client controlled, so this arrives as whatever anyone chose to
    send. The value is always bound as a parameter rather than interpolated, so
    this is not what stands between the request and an injection; it is what
    keeps a junk cookie from costing a round trip to the database.
    """
    if not user_id:
        return False
    try:
        return str(uuid.UUID(user_id)) == user_id
    except ValueError:
        return False


async def identify(env, cookie_header: str | None) -> tuple[dict, bool]:
    """Returns the visitor's row, creating one if this is somebody new.

    The second value says whether the caller has to send a cookie back, which
    only happens on the request that created the row.
    """
    user_id = read_cookie(cookie_header)

    if looks_like_ours(user_id):
        row = await query_one(
            env,
            "SELECT id, discovery_ratio, onboarded_at FROM users WHERE id = ?",
            [user_id],
        )
        if row:
            return row, False

    return await create(env), True


async def create(env) -> dict:
    """Opens a profile for a visitor the corpus has never seen.

    The empty `user_profile` row is written now rather than on the first like,
    so every later read can assume it exists instead of handling absence.
    """
    user_id = str(uuid.uuid4())
    created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    await execute(
        env,
        "INSERT INTO users (id, created_at) VALUES (?, ?)",
        [user_id, created_at],
    )
    await execute(
        env,
        "INSERT INTO user_profile (user_id, updated_at) VALUES (?, ?)",
        [user_id, created_at],
    )

    # A visitor who has just been created has answered nothing, which is what
    # the onboarding reads to decide whether it owes them a screen.
    return {"id": user_id, "discovery_ratio": 0.15, "onboarded_at": None}
