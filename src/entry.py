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
from urllib.parse import urlparse

from workers import Response

from api import feed, profile, users
from api.db import execute, query_one

# What a reader is allowed to record. `hide` is an exclusion in this slice and a
# negative vector in a later one, but either way it is the same event in the
# same table.
RECORDABLE = frozenset({"like", "hide"})


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
    user, is_new = await users.identify(env, request.headers.get("Cookie"))

    stored, avoided = await profile.load(env, user["id"])
    answered = await profile.acted_on(env, user["id"])
    cards = await feed.build(env, stored, avoided, answered, datetime.now(UTC))

    headers = {
        # Personalized, so it must never be held by a cache between the reader
        # and the Worker.
        "Cache-Control": "private, no-store",
    }
    if is_new:
        headers["Set-Cookie"] = users.set_cookie(user["id"])

    return Response.json(
        {
            "user": {"is_new": is_new, "discovery_ratio": user["discovery_ratio"]},
            "profile": {
                "terms": len(stored),
                "empty": not stored,
                "hidden_terms": len(avoided),
            },
            "feed": cards,
        },
        headers=headers,
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

    headers = {"Cache-Control": "private, no-store"}
    if is_new:
        headers["Set-Cookie"] = users.set_cookie(user["id"])

    return Response.json(
        {"ok": True, "profile": {"terms": len(vector), "hidden_terms": len(avoided)}},
        headers=headers,
    )


ROUTES = {
    ("GET", "/api/health"): health,
    ("GET", "/api/feed"): read_feed,
    ("POST", "/api/interactions"): record,
}


async def on_fetch(request, env):
    path = urlparse(request.url).path
    handler = ROUTES.get((request.method, path))

    if handler is None:
        return Response.json({"error": "not found"}, status=404)

    return await handler(request, env)
