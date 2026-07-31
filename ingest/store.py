"""Talks to D1 over HTTP.

The Worker reaches the same database through a binding. The ingestion job runs
in GitHub Actions, outside Cloudflare, so it uses the HTTP API instead.
"""

import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

API_ROOT = "https://api.cloudflare.com/client/v4"

# D1 accepts at most 100 bound parameters per query, so a multi-row insert is
# capped by how many columns it carries. Interpolating values into the SQL to
# dodge the limit would be an injection hole and would defeat statement reuse.
MAX_BOUND_PARAMS = 100


class D1Error(RuntimeError):
    pass


def chunked(items: Sequence[Any], size: int) -> Iterator[list]:
    """Splits a sequence into lists of at most `size`."""
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def _http_post(url: str, json: dict, headers: dict) -> dict:
    response = httpx.post(url, json=json, headers=headers, timeout=60.0)
    return response.json()


@dataclass
class D1Client:
    account_id: str
    database_id: str
    api_token: str
    post: Any = field(default=_http_post)

    @classmethod
    def from_env(cls) -> "D1Client":
        return cls(
            account_id=os.environ["CLOUDFLARE_ACCOUNT_ID"],
            database_id=os.environ["D1_DATABASE_ID"],
            api_token=os.environ["CLOUDFLARE_API_TOKEN"],
        )

    @property
    def _url(self) -> str:
        return f"{API_ROOT}/accounts/{self.account_id}/d1/database/{self.database_id}/query"

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        """Runs one statement and returns its rows.

        A failed call raises. Returning an empty list on failure would be
        indistinguishable from an empty corpus, and the job would quietly
        report success while writing nothing.
        """
        payload = {"sql": sql, "params": params or []}
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        body = self.post(self._url, json=payload, headers=headers)

        if not body.get("success"):
            errors = body.get("errors") or [{"message": "unknown D1 error"}]
            raise D1Error("; ".join(e.get("message", str(e)) for e in errors))

        result = body.get("result") or [{}]
        return result[0].get("results") or []

    def insert_many(self, table: str, columns: Sequence[str], rows: Sequence[Sequence]) -> None:
        """Writes rows as multi-row inserts, split to respect the bind limit.

        One request per row would mean thousands of round trips per run, which
        is the difference between a job that finishes in seconds and one that
        times out.
        """
        if not rows:
            return

        rows_per_request = max(1, MAX_BOUND_PARAMS // len(columns))
        placeholder = f"({', '.join('?' * len(columns))})"
        column_list = ", ".join(columns)

        for chunk in chunked(rows, rows_per_request):
            values = ", ".join([placeholder] * len(chunk))
            params = [value for row in chunk for value in row]
            self.query(
                f"INSERT OR IGNORE INTO {table} ({column_list}) VALUES {values}",
                params,
            )
