import json
import sqlite3
from pathlib import Path


class Repository:
    """Small persistent store. One connection per operation, suitable for local development."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS entities "
                "(kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind, id))"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def put(self, kind: str, identifier: str, value: dict):
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO entities VALUES (?, ?, ?) "
                "ON CONFLICT(kind, id) DO UPDATE SET payload=excluded.payload",
                (kind, identifier, json.dumps(value, allow_nan=False)),
            )

    def get(self, kind: str, identifier: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM entities WHERE kind=? AND id=?", (kind, identifier)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM entities WHERE kind=? ORDER BY rowid DESC", (kind,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
