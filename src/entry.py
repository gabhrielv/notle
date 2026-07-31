"""Worker entrypoint.

Only /api/* reaches this module. Everything else is served straight from the
built front by the platform, without invoking Worker code at all.
"""

import asgi
from fastapi import FastAPI

from api.db import query_one

# No docs, no redoc, no OpenAPI schema. This is a public demo with three routes,
# and each of those endpoints would be surface area with nothing behind it.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/health")
async def health(env=asgi.env):
    """Exercises the whole path down to the database, not just the runtime."""
    row = await query_one(env, "SELECT COUNT(*) AS n FROM articles")
    return {"ok": True, "articles": row["n"]}


async def on_fetch(request, env):
    return await asgi.fetch(app, request, env)
