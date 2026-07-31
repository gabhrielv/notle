"""The only module that touches the D1 binding.

Everything below the API speaks plain Python dicts and lists. The JS interop
lives here so that a change in how Pyodide exposes bindings costs one file
instead of a search across the codebase.
"""

# D1 binds at most 100 parameters per statement. Anything built from a list the
# request did not choose the length of has to be split against this.
MAX_BOUND_PARAMS = 100


def _to_rows(result):
    """Turn a D1 result into a list of plain Python dicts.

    `result` arrives as a JsProxy. `.results` is a JS array of objects, and
    each object needs converting before Python can index it by key.
    """
    results = result.results
    if results is None:
        return []
    rows = results.to_py()
    return [dict(row) for row in rows]


async def query(env, sql, params=None):
    """Run a read and return every row."""
    stmt = env.DB.prepare(sql)
    if params:
        stmt = stmt.bind(*params)
    return _to_rows(await stmt.all())


async def query_one(env, sql, params=None):
    """Run a read and return the first row, or None."""
    rows = await query(env, sql, params)
    return rows[0] if rows else None


async def execute(env, sql, params=None):
    """Run a write. Returns the number of rows the statement touched."""
    stmt = env.DB.prepare(sql)
    if params:
        stmt = stmt.bind(*params)
    result = await stmt.run()
    return result.meta.changes
