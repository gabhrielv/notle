"""Worker entrypoint.

Only /api/* reaches this module. Everything else is served straight from the
built front by the platform, without invoking Worker code at all.

No web framework here, and that is a platform constraint rather than a taste.
A Python Worker gets 1000ms of startup CPU, and importing FastAPI costs 1710ms
on its own, so the deploy is rejected outright. Deferring the import into the
handler only moves that cost into the request, where the ceiling is far lower.
With three routes, no schema surface and no OpenAPI to serve, the routing a
framework would have done fits in the function below.
"""

from urllib.parse import urlparse

from workers import Response

from api.db import query_one


async def health(env):
    """Exercises the whole path down to the database, not just the runtime."""
    row = await query_one(env, "SELECT COUNT(*) AS n FROM articles")
    return Response.json({"ok": True, "articles": row["n"]})


ROUTES = {
    ("GET", "/api/health"): health,
}


async def on_fetch(request, env):
    path = urlparse(request.url).path
    handler = ROUTES.get((request.method, path))

    if handler is None:
        return Response.json({"error": "not found"}, status=404)

    return await handler(env)
