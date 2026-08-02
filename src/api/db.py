"""The only module that touches the D1 binding.

Everything below the API speaks plain Python dicts and lists. The JS interop
lives here so that a change in how Pyodide exposes bindings costs one file
instead of a search across the codebase.
"""

# D1 binds at most 100 parameters per statement. Anything built from a list the
# request did not choose the length of has to be split against this.
MAX_BOUND_PARAMS = 100


def _without_nulls(sql: str, params):
    """Moves every `None` out of the parameters and into the statement.

    A nullable column cannot otherwise be written from Python at all. `None`
    crosses into JavaScript as `undefined` and D1 refuses it outright with
    `D1_TYPE_ERROR: Type 'undefined' not supported`, and there is no way to hand
    it a real `null` instead: the runtime exposes none to import, `to_js(None)`
    produces `undefined` again, and a `null` parsed out of JSON converts back to
    `None` on the way in. So the value has to stop being a value and become
    syntax.

    The first column that needed it was `interactions.session_id`, where every
    batch of signals sent without a session died on the insert.

    Positional, so it depends on the count of placeholders matching the count of
    parameters. When it does not, the statement is handed back untouched: a
    mismatch is a bug worth surfacing as the database's own error rather than
    something to paper over by rewriting SQL on a guess.
    """
    if not any(value is None for value in params):
        return sql, list(params)

    pieces = sql.split("?")
    if len(pieces) - 1 != len(params):
        return sql, list(params)

    rebuilt = [pieces[0]]
    kept = []
    for value, piece in zip(params, pieces[1:], strict=True):
        if value is None:
            rebuilt.append("NULL")
        else:
            rebuilt.append("?")
            kept.append(value)
        rebuilt.append(piece)

    return "".join(rebuilt), kept


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
    if params:
        sql, params = _without_nulls(sql, params)

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
    if params:
        sql, params = _without_nulls(sql, params)

    stmt = env.DB.prepare(sql)
    if params:
        stmt = stmt.bind(*params)
    result = await stmt.run()
    return result.meta.changes
