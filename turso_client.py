"""
Lightweight Turso HTTP client — talks to Turso's HTTP API using requests.
Returns sqlite3.Row-compatible results so existing code works unchanged.
No native dependencies needed (pure Python, uses requests).
"""

import os
import sqlite3
import requests


class TursoRow:
    """Mimics sqlite3.Row so existing code using row['column'] works."""

    def __init__(self, columns, values):
        self._data = dict(zip(columns, values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]

    def keys(self):
        return list(self._data.keys())

    def __iter__(self):
        return iter(self._data.values())

    def __len__(self):
        return len(self._data)


class TursoCursor:
    """Minimal cursor that stores results from Turso HTTP API."""

    def __init__(self, rows, columns, lastrowid=None, rowcount=-1):
        self._rows = rows
        self._columns = columns
        self.lastrowid = lastrowid
        self.rowcount = rowcount
        self.description = [(c, None, None, None, None, None, None) for c in columns] if columns else None

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class TursoConnection:
    """HTTP-based connection to Turso that mimics sqlite3.Connection."""

    def __init__(self, url, auth_token):
        # Convert libsql:// to https://
        self.url = url.replace("libsql://", "https://")
        self.auth_token = auth_token
        self.row_factory = None  # kept for compatibility, we always return TursoRow

    def _request(self, sql, params=None):
        """Execute a single SQL statement via Turso HTTP API."""
        endpoint = f"{self.url}/v2/pipeline"
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
        }

        # Build the request
        if params:
            args = []
            for p in params:
                if p is None:
                    args.append({"type": "null", "value": None})
                elif isinstance(p, int):
                    args.append({"type": "integer", "value": str(p)})
                elif isinstance(p, float):
                    args.append({"type": "float", "value": p})
                else:
                    args.append({"type": "text", "value": str(p)})
            stmt = {"type": "execute", "stmt": {"sql": sql, "args": args}}
        else:
            stmt = {"type": "execute", "stmt": {"sql": sql}}

        body = {"requests": [stmt, {"type": "close"}]}
        resp = requests.post(endpoint, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Parse response
        results = data.get("results", [])
        if not results:
            return [], [], 0, None

        result = results[0]
        if result.get("type") == "error":
            error_msg = result.get("error", {}).get("message", "Unknown Turso error")
            raise sqlite3.OperationalError(error_msg)

        response = result.get("response", {}).get("result", {})
        cols = [c.get("name", "") for c in response.get("cols", [])]
        raw_rows = response.get("rows", [])
        affected = response.get("affected_row_count", 0)
        last_id = response.get("last_insert_rowid", None)

        rows = []
        for raw_row in raw_rows:
            values = [cell.get("value") for cell in raw_row]
            rows.append(TursoRow(cols, values))

        return rows, cols, affected, last_id

    def execute(self, sql, params=None):
        rows, cols, affected, last_id = self._request(sql, params)
        return TursoCursor(rows, cols, lastrowid=last_id, rowcount=affected)

    def executescript(self, sql):
        """Execute multiple SQL statements separated by semicolons."""
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for stmt in statements:
            self._request(stmt)

    def cursor(self):
        return self

    def commit(self):
        pass  # Turso auto-commits

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
