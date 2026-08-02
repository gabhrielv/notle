"""Worker entrypoint.

Only /api/* reaches this module. Everything else is served straight from the
built front by the platform, without invoking Worker code at all.

No web framework here, and that is a platform constraint rather than a taste.
A Python Worker gets 1000ms of startup CPU, and importing FastAPI costs 1710ms
on its own, so the deploy is rejected outright. Deferring the import into the
handler only moves that cost into the request, where the ceiling is far lower.
With a handful of routes, no schema surface and no OpenAPI to serve, the routing
a framework would have done fits in the function below.
"""

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from workers import Response

from api import browse, feed, onboarding, profile, users
from api.db import execute, query_one

# What a reader is allowed to record. A hide both excludes its own cluster and
# feeds the negative vector, but either way it is the same event in the same
# table.
RECORDABLE = frozenset({"like", "hide"})

# Personalized, so it must never be held by a cache between reader and Worker.
PRIVATE = {"Cache-Control": "private, no-store"}


def _params(request) -> dict[str, list[str]]:
    return parse_qs(urlparse(request.url).query)


def _one(params: dict, name: str, fallback: str = "") -> str:
    return params.get(name, [fallback])[0]


def _offset(params: dict) -> int:
    """Where the reader has scrolled to.

    Anything that is not a whole number is read as the start rather than
    refused. The offset comes from a scroll position, and a malformed one is a
    bug in the caller, not something the reader can act on.
    """
    raw = _one(params, "offset", "0")
    return int(raw) if raw.isdigit() else 0


async def health(request, env):
    """Exercises the whole path down to the database, not just the runtime."""
    row = await query_one(env, "SELECT COUNT(*) AS n FROM articles")
    return Response.json({"ok": True, "articles": row["n"]})


async def read_feed(request, env):
    """User, profile and feed in one call.

    Three endpoints would mean the browser waiting for the first before it knows
    to ask for the second, and a cascade of round trips on the one screen that
    decides whether a visitor stays.
    """
    params = _params(request)
    offset = _offset(params)

    user, is_new = await users.identify(env, request.headers.get("Cookie"))

    stored, avoided = await profile.load(env, user["id"])
    answered = await profile.acted_on(env, user["id"])
    cards = await feed.build(env, stored, avoided, answered, datetime.now(UTC), offset)

    # The cold start rides along rather than being asked for separately. A
    # visitor who has answered nothing is the visitor this screen has to be
    # fastest for, and fetching the headlines in a second call would put a round
    # trip in front of the one screen that decides whether they stay. It costs a
    # returning reader nothing: `pending` is false and the query never runs.
    owed = offset == 0 and await onboarding.pending(env, user)

    headers = dict(PRIVATE)
    if is_new:
        headers["Set-Cookie"] = users.set_cookie(user["id"])

    return Response.json(
        {
            "user": {"is_new": is_new, "discovery_ratio": user["discovery_ratio"]},
            "onboarding": {
                "pending": owed,
                "picks": onboarding.PICKS,
                "feed": await onboarding.offer(env) if owed else [],
            },
            "profile": {
                "terms": len(stored),
                "empty": not stored,
                "hidden_terms": len(avoided),
            },
            "feed": cards,
            # Absent rather than false when the page came back short: the client
            # stops asking, which is what ends an endless scroll.
            "next_offset": offset + len(cards) if len(cards) >= feed.PAGE else None,
        },
        headers=headers,
    )


async def write_onboarding(request, env):
    """Records what was chosen, or that nothing was.

    Both answers mark the reader as done. Skipping has to be an answer the
    system accepts, or the only way past a screen that will not take no is the
    close button.
    """
    user, is_new = await users.identify(env, request.headers.get("Cookie"))

    try:
        body = json.loads(await request.text())
    except ValueError:
        return Response.json({"error": "corpo invalido"}, status=400)

    chosen = await onboarding.answer(env, user["id"], body.get("picks"))
    vector, _ = await profile.rebuild(env, user["id"])

    headers = dict(PRIVATE)
    if is_new:
        headers["Set-Cookie"] = users.set_cookie(user["id"])

    return Response.json(
        {"ok": True, "chosen": chosen, "profile": {"terms": len(vector)}},
        headers=headers,
    )


async def read_latest(request, env):
    """Everything the corpus holds, newest first, with no ranking at all.

    Hidden clusters are left out by default and returned when asked for, because
    a hide is an instruction about the feed and this page is the place to check
    what that instruction is costing.
    """
    params = _params(request)
    offset = _offset(params)
    show_hidden = _one(params, "hidden") == "1"

    user, is_new = await users.identify(env, request.headers.get("Cookie"))
    hidden = set() if show_hidden else await profile.hidden(env, user["id"])

    cards = await browse.latest(env, offset, hidden)

    headers = dict(PRIVATE)
    if is_new:
        headers["Set-Cookie"] = users.set_cookie(user["id"])

    return Response.json(
        {
            "feed": cards,
            "hidden_shown": show_hidden,
            "hidden_count": len(hidden) if not show_hidden else 0,
            "next_offset": offset + len(cards) if len(cards) >= browse.PAGE else None,
        },
        headers=headers,
    )


async def read_search(request, env):
    """Stories matching what was typed.

    Nothing here reads or writes a profile, in either mode. The anonymous switch
    is a promise the client keeps by not offering the buttons that record, and
    this endpoint is the same either way, so the promise is one the server cannot
    break by accident.
    """
    params = _params(request)
    offset = _offset(params)
    typed = _one(params, "q").strip()

    cards = await browse.search(env, typed, offset) if typed else []

    return Response.json(
        {
            "query": typed,
            "feed": cards,
            "next_offset": offset + len(cards) if len(cards) >= browse.PAGE else None,
        },
        headers=PRIVATE,
    )


async def record(request, env):
    """Stores one explicit signal and rebuilds the profile from the log."""
    user, is_new = await users.identify(env, request.headers.get("Cookie"))

    try:
        body = json.loads(await request.text())
    except ValueError:
        return Response.json({"error": "corpo invalido"}, status=400)

    kind = body.get("type")
    cluster_id = body.get("cluster_id")

    if kind not in RECORDABLE:
        return Response.json({"error": "tipo desconhecido"}, status=400)
    if not isinstance(cluster_id, int):
        return Response.json({"error": "cluster_id ausente"}, status=400)

    # The foreign key is on articles, not on interactions.cluster_id, so an id
    # that never existed would otherwise be stored and then poison the profile
    # rebuild with a join that matches nothing.
    known = await query_one(env, "SELECT id FROM clusters WHERE id = ?", [cluster_id])
    if known is None:
        return Response.json({"error": "cluster inexistente"}, status=404)

    await execute(
        env,
        "INSERT INTO interactions (user_id, cluster_id, type, value, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            user["id"],
            cluster_id,
            kind,
            profile.WEIGHTS.get(kind, 1.0),
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ],
    )

    vector, avoided = await profile.rebuild(env, user["id"])

    headers = dict(PRIVATE)
    if is_new:
        headers["Set-Cookie"] = users.set_cookie(user["id"])

    return Response.json(
        {"ok": True, "profile": {"terms": len(vector), "hidden_terms": len(avoided)}},
        headers=headers,
    )


ROUTES = {
    ("GET", "/api/health"): health,
    ("GET", "/api/feed"): read_feed,
    ("GET", "/api/latest"): read_latest,
    ("GET", "/api/search"): read_search,
    ("POST", "/api/onboarding"): write_onboarding,
    ("POST", "/api/interactions"): record,
}


async def on_fetch(request, env):
    path = urlparse(request.url).path
    handler = ROUTES.get((request.method, path))

    if handler is None:
        return Response.json({"error": "not found"}, status=404)

    return await handler(request, env)
