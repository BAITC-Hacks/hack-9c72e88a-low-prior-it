import json
import sqlite3
from pathlib import Path
from threading import RLock

from wind_agent.interfaces import ForecastError


class Storage:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,id))")
        self.db.commit()

    def insert(self, kind: str, value: dict):
        with self.lock, self.db:
            try:
                self.db.execute("INSERT INTO records VALUES (?,?,?)", (kind, value["id"], json.dumps(value, allow_nan=False)))
            except sqlite3.IntegrityError as exc:
                raise ForecastError("immutable_record", f"{kind}/{value['id']} already exists") from exc

    def get(self, kind: str, identity: str):
        with self.lock:
            row = self.db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, identity)).fetchone()
        if row is None:
            raise ForecastError("not_found", f"Unknown {kind}: {identity}", 404)
        return json.loads(row[0])

    def list(self, kind: str):
        with self.lock:
            rows = self.db.execute("SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update_job(self, kind: str, value: dict):
        if kind not in ("forecast", "backtest"):
            raise ValueError("only job state may be updated")
        with self.lock, self.db:
            self.db.execute("UPDATE records SET payload=? WHERE kind=? AND id=?",
                            (json.dumps(value, allow_nan=False), kind, value["id"]))

    def recover(self):
        for kind in ("forecast", "backtest"):
            for value in self.list(kind):
                if value["status"] in ("queued", "running"):
                    value.update(status="failed", error={"code": "process_restarted", "message": "Process restarted before job completed. Submit again."})
                    self.update_job(kind, value)

    def close(self):
        with self.lock:
            self.db.close()
