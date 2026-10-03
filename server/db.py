"""SQLite (stdlib) con migraciones numeradas por `PRAGMA user_version`."""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # 1 — equipos (agentes) y dispositivos con color estable
    """
    CREATE TABLE hosts (
        id INTEGER PRIMARY KEY,
        agent_url TEXT NOT NULL UNIQUE,
        name TEXT,
        token TEXT,
        host_id TEXT,
        info TEXT,
        created_at REAL NOT NULL,
        last_seen_at REAL
    );
    CREATE TABLE devices (
        device_id TEXT PRIMARY KEY,
        host_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        kind TEXT NOT NULL,
        name TEXT,
        color_index INTEGER,
        info TEXT,
        first_seen_at REAL NOT NULL,
        last_seen_at REAL NOT NULL
    );
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]

#: Tamaño de la paleta de dispositivos de la GUI (--dev-1 … --dev-N).
DEVICE_PALETTE_SIZE = 6


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.migrate()

    def migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            self.conn.executescript(f"BEGIN;{sql};PRAGMA user_version={i};COMMIT;")

    def close(self) -> None:
        self.conn.close()

    # --- hosts -------------------------------------------------------------

    def list_hosts(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM hosts ORDER BY id").fetchall()
        return [_host(r) for r in rows]

    def get_host(self, host_pk: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM hosts WHERE id=?", (host_pk,)).fetchone()
        return _host(row) if row else None

    def add_host(self, agent_url: str, name: str | None = None, token: str | None = None) -> dict[str, Any]:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO hosts(agent_url, name, token, created_at) VALUES (?,?,?,?)",
                (agent_url, name, token, time.time()),
            )
            return self.get_host(cur.lastrowid)

    def ensure_host(self, agent_url: str) -> dict[str, Any]:
        with self.lock:
            row = self.conn.execute("SELECT * FROM hosts WHERE agent_url=?", (agent_url,)).fetchone()
            return _host(row) if row else self.add_host(agent_url)

    def delete_host(self, host_pk: int) -> bool:
        with self.lock:
            return self.conn.execute("DELETE FROM hosts WHERE id=?", (host_pk,)).rowcount > 0

    def save_host_info(self, host_pk: int, info: dict[str, Any]) -> None:
        host_id = (info.get("host") or {}).get("host_id")
        with self.lock:
            self.conn.execute(
                "UPDATE hosts SET info=?, host_id=?, last_seen_at=? WHERE id=?",
                (json.dumps(info), host_id, time.time(), host_pk),
            )

    def touch_host(self, host_pk: int) -> None:
        with self.lock:
            self.conn.execute("UPDATE hosts SET last_seen_at=? WHERE id=?", (time.time(), host_pk))

    # --- devices -----------------------------------------------------------

    def upsert_devices(self, host_id: str, devices: list[dict[str, Any]]) -> dict[str, int | None]:
        """Registra dispositivos y devuelve {device_id: color_index}.

        El color se asigna la primera vez que se ve un dispositivo (el índice
        libre más bajo entre las GPU conocidas) y no cambia nunca después.
        """
        now = time.time()
        colors: dict[str, int | None] = {}
        with self.lock:
            for d in devices:
                row = self.conn.execute(
                    "SELECT color_index FROM devices WHERE device_id=?", (d["device_id"],)
                ).fetchone()
                if row is None:
                    color = self._next_color() if d.get("kind") == "gpu" else None
                    self.conn.execute(
                        "INSERT INTO devices(device_id, host_id, provider, kind, name, color_index, info,"
                        " first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            d["device_id"],
                            host_id,
                            d["provider"],
                            d["kind"],
                            d.get("name"),
                            color,
                            json.dumps(d),
                            now,
                            now,
                        ),
                    )
                else:
                    color = row["color_index"]
                    self.conn.execute(
                        "UPDATE devices SET host_id=?, name=?, info=?, last_seen_at=? WHERE device_id=?",
                        (host_id, d.get("name"), json.dumps(d), now, d["device_id"]),
                    )
                colors[d["device_id"]] = color
        return colors

    def _next_color(self) -> int:
        used = [
            r[0] for r in self.conn.execute("SELECT color_index FROM devices WHERE color_index IS NOT NULL")
        ]
        for i in range(DEVICE_PALETTE_SIZE):
            if i not in used:
                return i
        return len(used) % DEVICE_PALETTE_SIZE  # más dispositivos que colores: se reparten en ciclo

    def list_devices(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM devices ORDER BY first_seen_at").fetchall()
        return [{**dict(r), "info": json.loads(r["info"]) if r["info"] else None} for r in rows]


def _host(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["info"] = json.loads(d["info"]) if d.get("info") else None
    return d
