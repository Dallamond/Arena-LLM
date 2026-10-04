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
    # 2 — servidores detectados, cambios de configuración y pruebas (runs)
    """
    CREATE TABLE endpoints (
        id INTEGER PRIMARY KEY,
        host_pk INTEGER NOT NULL,
        base_url TEXT NOT NULL UNIQUE,
        alias TEXT,
        engine TEXT,
        status TEXT,
        fingerprint TEXT,
        snapshot TEXT,
        first_seen_at REAL NOT NULL,
        last_seen_at REAL NOT NULL
    );
    CREATE TABLE config_changes (
        id INTEGER PRIMARY KEY,
        endpoint_id INTEGER NOT NULL,
        t REAL NOT NULL,
        kind TEXT NOT NULL,
        diff TEXT,
        snapshot TEXT
    );
    CREATE INDEX config_changes_ep ON config_changes(endpoint_id, t);
    CREATE TABLE runs (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        suite TEXT NOT NULL,
        suite_version TEXT,
        suite_hash TEXT,
        label TEXT,
        status TEXT NOT NULL,
        host_pk INTEGER,
        endpoint_id INTEGER,
        params TEXT,
        servers_snapshot TEXT,
        host_snapshot TEXT,
        created_at REAL NOT NULL,
        started_at REAL,
        finished_at REAL,
        summary TEXT,
        error TEXT,
        abort_reason TEXT,
        notes TEXT,
        tags TEXT
    );
    CREATE TABLE items (
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        name TEXT,
        prompt TEXT,
        response TEXT,
        reasoning TEXT,
        metrics TEXT,
        eval TEXT,
        error TEXT,
        started_at REAL,
        finished_at REAL
    );
    CREATE INDEX items_run ON items(run_id, idx);
    CREATE TABLE samples (
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        t REAL NOT NULL,
        phase TEXT NOT NULL,
        device_id TEXT NOT NULL,
        data TEXT NOT NULL
    );
    CREATE INDEX samples_run ON samples(run_id, t);
    CREATE TABLE tps_series (
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        t REAL NOT NULL,
        tokens INTEGER NOT NULL,
        tps REAL NOT NULL
    );
    CREATE INDEX tps_run ON tps_series(run_id, t);
    """,
    # 3 — un servidor se identifica por equipo + URL (dos equipos pueden usar el mismo puerto local)
    """
    CREATE TABLE endpoints_v3 (
        id INTEGER PRIMARY KEY,
        host_pk INTEGER NOT NULL,
        base_url TEXT NOT NULL,
        alias TEXT,
        engine TEXT,
        status TEXT,
        fingerprint TEXT,
        snapshot TEXT,
        first_seen_at REAL NOT NULL,
        last_seen_at REAL NOT NULL,
        UNIQUE(host_pk, base_url)
    );
    INSERT INTO endpoints_v3 SELECT * FROM endpoints;
    DROP TABLE endpoints;
    ALTER TABLE endpoints_v3 RENAME TO endpoints;
    """,
    # 4 — alta manual de endpoints y GPU asociadas a mano (cuando la detección no las da)
    """
    ALTER TABLE endpoints ADD COLUMN manual INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE endpoints ADD COLUMN device_ids TEXT;
    """,
    # 5 — filas de llama-bench (rendimiento por componente)
    """
    CREATE TABLE bench_rows (
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        test TEXT NOT NULL,
        n_prompt INTEGER,
        n_gen INTEGER,
        n_depth INTEGER,
        params TEXT,
        t_s_mean REAL,
        t_s_std REAL,
        reps INTEGER,
        samples TEXT,
        t REAL,
        derived TEXT,
        raw TEXT
    );
    CREATE INDEX bench_rows_run ON bench_rows(run_id, idx);
    """,
    # 6 — batallas: varios runs (lados) con los mismos prompts
    """
    CREATE TABLE battles (
        id INTEGER PRIMARY KEY,
        label TEXT,
        mode TEXT NOT NULL,
        status TEXT NOT NULL,
        params TEXT,
        sides TEXT,
        error TEXT,
        created_at REAL NOT NULL,
        finished_at REAL
    );
    ALTER TABLE runs ADD COLUMN battle_id INTEGER;
    ALTER TABLE runs ADD COLUMN side TEXT;
    CREATE INDEX runs_battle ON runs(battle_id);
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
        used = [r[0] for r in self.conn.execute("SELECT color_index FROM devices WHERE color_index IS NOT NULL")]
        for i in range(DEVICE_PALETTE_SIZE):
            if i not in used:
                return i
        return len(used) % DEVICE_PALETTE_SIZE  # más dispositivos que colores: se reparten en ciclo

    def list_devices(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM devices ORDER BY first_seen_at").fetchall()
        return [{**dict(r), "info": json.loads(r["info"]) if r["info"] else None} for r in rows]

    # --- ajustes -----------------------------------------------------------

    def get_settings(self) -> dict[str, Any]:
        with self.lock:
            rows = self.conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    # --- servidores detectados (endpoints) ---------------------------------

    def upsert_endpoint(
        self,
        host_pk: int,
        base_url: str,
        engine: str,
        status: str,
        fingerprint: str,
        snapshot: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        """Guarda la detección. Devuelve (endpoint, tipo de cambio: 'nuevo' | 'cambio' | None)."""
        now = time.time()
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM endpoints WHERE host_pk=? AND base_url=?", (host_pk, base_url)
            ).fetchone()
            if row is None:
                cur = self.conn.execute(
                    "INSERT INTO endpoints(host_pk, base_url, engine, status, fingerprint, snapshot,"
                    " first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?)",
                    (host_pk, base_url, engine, status, fingerprint, json.dumps(snapshot), now, now),
                )
                change = "nuevo"
                ep_id = cur.lastrowid
            else:
                ep_id = row["id"]
                change = "cambio" if row["fingerprint"] != fingerprint else None
                self.conn.execute(
                    "UPDATE endpoints SET host_pk=?, engine=?, status=?, fingerprint=?, snapshot=?, last_seen_at=?"
                    " WHERE id=?",
                    (host_pk, engine, status, fingerprint, json.dumps(snapshot), now, ep_id),
                )
            return self.get_endpoint(ep_id), change

    def add_manual_endpoint(
        self, host_pk: int, base_url: str, alias: str | None, device_ids: list[str] | None
    ) -> dict[str, Any]:
        """Alta a mano. Si ya existe (p. ej. detectado), se marca como manual y se conservan sus datos."""
        now = time.time()
        with self.lock:
            row = self.conn.execute(
                "SELECT id FROM endpoints WHERE host_pk=? AND base_url=?", (host_pk, base_url)
            ).fetchone()
            if row is None:
                cur = self.conn.execute(
                    "INSERT INTO endpoints(host_pk, base_url, alias, engine, status, fingerprint, snapshot,"
                    " first_seen_at, last_seen_at, manual, device_ids) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                    (host_pk, base_url, alias, "llama.cpp", "sin respuesta", "", None, now, now,
                     json.dumps(device_ids) if device_ids is not None else None),
                )  # fmt: skip
                ep_id = cur.lastrowid
            else:
                ep_id = row["id"]
                self.conn.execute(
                    "UPDATE endpoints SET manual=1, alias=COALESCE(?, alias),"
                    " device_ids=COALESCE(?, device_ids) WHERE id=?",
                    (alias, json.dumps(device_ids) if device_ids is not None else None, ep_id),
                )
            return self.get_endpoint(ep_id)

    def set_endpoint_devices(self, endpoint_id: int, device_ids: list[str] | None) -> None:
        """GPU asociadas a mano (`None` = usar la detección)."""
        with self.lock:
            self.conn.execute(
                "UPDATE endpoints SET device_ids=? WHERE id=?",
                (json.dumps(device_ids) if device_ids is not None else None, endpoint_id),
            )

    def delete_endpoint(self, endpoint_id: int) -> None:
        """Borra el servidor y su historial de cambios. Los runs conservan su foto de configuración."""
        with self.lock:
            self.conn.execute("DELETE FROM config_changes WHERE endpoint_id=?", (endpoint_id,))
            self.conn.execute("DELETE FROM endpoints WHERE id=?", (endpoint_id,))

    def set_endpoint_status(self, endpoint_id: int, status: str) -> None:
        with self.lock:
            self.conn.execute("UPDATE endpoints SET status=? WHERE id=?", (status, endpoint_id))

    def set_endpoint_alias(self, endpoint_id: int, alias: str | None) -> None:
        with self.lock:
            self.conn.execute("UPDATE endpoints SET alias=? WHERE id=?", (alias, endpoint_id))

    def get_endpoint(self, endpoint_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM endpoints WHERE id=?", (endpoint_id,)).fetchone()
        return _endpoint(row) if row else None

    def list_endpoints(self, host_pk: int | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM endpoints", ()
        if host_pk is not None:
            sql, args = sql + " WHERE host_pk=?", (host_pk,)
        with self.lock:
            rows = self.conn.execute(sql + " ORDER BY base_url", args).fetchall()
        return [_endpoint(r) for r in rows]

    def add_config_change(
        self, endpoint_id: int, kind: str, diff: dict[str, Any] | None, snapshot: dict[str, Any] | None
    ) -> dict[str, Any]:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO config_changes(endpoint_id, t, kind, diff, snapshot) VALUES (?,?,?,?,?)",
                (endpoint_id, time.time(), kind, json.dumps(diff), json.dumps(snapshot)),
            )
            row = self.conn.execute("SELECT * FROM config_changes WHERE id=?", (cur.lastrowid,)).fetchone()
        return _json_cols(row, "diff", "snapshot")

    def list_config_changes(self, endpoint_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM config_changes", ()
        if endpoint_id is not None:
            sql, args = sql + " WHERE endpoint_id=?", (endpoint_id,)
        with self.lock:
            rows = self.conn.execute(sql + " ORDER BY t DESC LIMIT ?", (*args, limit)).fetchall()
        return [_json_cols(r, "diff", "snapshot") for r in rows]

    # --- runs --------------------------------------------------------------

    RUN_JSON = ("params", "servers_snapshot", "host_snapshot", "summary", "tags")

    def create_run(self, **fields: Any) -> dict[str, Any]:
        fields.setdefault("created_at", time.time())
        for k in self.RUN_JSON:
            if k in fields:
                fields[k] = json.dumps(fields[k])
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        with self.lock:
            cur = self.conn.execute(f"INSERT INTO runs({cols}) VALUES ({marks})", tuple(fields.values()))
        return self.get_run(cur.lastrowid)

    def update_run(self, run_id: int, **fields: Any) -> None:
        for k in self.RUN_JSON:
            if k in fields:
                fields[k] = json.dumps(fields[k])
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE runs SET {sets} WHERE id=?", (*fields.values(), run_id))

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return _json_cols(row, *self.RUN_JSON) if row else None

    def list_runs(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, kind, suite, suite_version, suite_hash, label, status, host_pk, endpoint_id, params,"
                " created_at, started_at, finished_at, summary, error, abort_reason, tags, battle_id, side"
                " FROM runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_json_cols(r, "params", "summary", "tags") for r in rows]

    def get_runs(self, run_ids: list[int]) -> list[dict[str, Any]]:
        """Varios runs completos, en el orden pedido (los que no existen se omiten)."""
        out = []
        for rid in run_ids:
            run = self.get_run(rid)
            if run:
                out.append(run)
        return out

    # --- batallas ------------------------------------------------------------

    BATTLE_JSON = ("params", "sides")

    def create_battle(self, **fields: Any) -> dict[str, Any]:
        fields.setdefault("created_at", time.time())
        for k in self.BATTLE_JSON:
            if k in fields:
                fields[k] = json.dumps(fields[k])
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        with self.lock:
            cur = self.conn.execute(f"INSERT INTO battles({cols}) VALUES ({marks})", tuple(fields.values()))
        return self.get_battle(cur.lastrowid)

    def update_battle(self, battle_id: int, **fields: Any) -> None:
        for k in self.BATTLE_JSON:
            if k in fields:
                fields[k] = json.dumps(fields[k])
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE battles SET {sets} WHERE id=?", (*fields.values(), battle_id))

    def get_battle(self, battle_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM battles WHERE id=?", (battle_id,)).fetchone()
        return _json_cols(row, *self.BATTLE_JSON) if row else None

    def list_battles(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM battles ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_json_cols(r, *self.BATTLE_JSON) for r in rows]

    def delete_battle(self, battle_id: int) -> bool:
        """Borra la batalla y sus runs."""
        with self.lock:
            self.conn.execute("DELETE FROM runs WHERE battle_id=?", (battle_id,))
            return self.conn.execute("DELETE FROM battles WHERE id=?", (battle_id,)).rowcount > 0

    def mark_interrupted_battles(self) -> int:
        with self.lock:
            return self.conn.execute(
                "UPDATE battles SET status='error', error='Servidor detenido durante la batalla', finished_at=?"
                " WHERE status IN ('pending', 'running')",
                (time.time(),),
            ).rowcount

    def delete_run(self, run_id: int) -> bool:
        with self.lock:
            return self.conn.execute("DELETE FROM runs WHERE id=?", (run_id,)).rowcount > 0

    def mark_interrupted_runs(self) -> int:
        """Runs que quedaron a medias por un cierre del servidor."""
        with self.lock:
            return self.conn.execute(
                "UPDATE runs SET status='error', error='Servidor detenido durante la prueba', finished_at=?"
                " WHERE status IN ('pending', 'running')",
                (time.time(),),
            ).rowcount

    def add_item(self, run_id: int, idx: int, **fields: Any) -> int:
        for k in ("metrics", "eval"):
            if k in fields:
                fields[k] = json.dumps(fields[k])
        cols = ", ".join(["run_id", "idx", *fields])
        marks = ", ".join("?" for _ in range(len(fields) + 2))
        with self.lock:
            cur = self.conn.execute(f"INSERT INTO items({cols}) VALUES ({marks})", (run_id, idx, *fields.values()))
        return cur.lastrowid

    def list_items(self, run_id: int) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM items WHERE run_id=? ORDER BY idx", (run_id,)).fetchall()
        return [_json_cols(r, "metrics", "eval") for r in rows]

    def add_samples(self, run_id: int, t: float, phase: str, devices: dict[str, Any]) -> None:
        with self.lock:
            self.conn.executemany(
                "INSERT INTO samples(run_id, t, phase, device_id, data) VALUES (?,?,?,?,?)",
                [(run_id, t, phase, dev, json.dumps(data)) for dev, data in devices.items()],
            )

    def list_samples(self, run_id: int) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT t, phase, device_id, data FROM samples WHERE run_id=? ORDER BY t", (run_id,)
            ).fetchall()
        return [_json_cols(r, "data") for r in rows]

    def add_tps(self, run_id: int, t: float, tokens: int, tps: float) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO tps_series(run_id, t, tokens, tps) VALUES (?,?,?,?)", (run_id, t, tokens, tps)
            )

    def list_tps(self, run_id: int) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT t, tokens, tps FROM tps_series WHERE run_id=? ORDER BY t", (run_id,)
            ).fetchall()
        return [dict(r) for r in rows]


    # --- filas de llama-bench ---------------------------------------------

    BENCH_JSON = ("params", "samples", "derived", "raw")

    def add_bench_row(self, run_id: int, idx: int, row: dict[str, Any]) -> None:
        fields = {k: (json.dumps(v) if k in self.BENCH_JSON else v) for k, v in row.items()}
        cols = ", ".join(["run_id", "idx", *fields])
        marks = ", ".join("?" for _ in range(len(fields) + 2))
        with self.lock:
            self.conn.execute(f"INSERT INTO bench_rows({cols}) VALUES ({marks})", (run_id, idx, *fields.values()))

    def list_bench_rows(self, run_id: int) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM bench_rows WHERE run_id=? ORDER BY idx", (run_id,)
            ).fetchall()
        return [_json_cols(r, *self.BENCH_JSON) for r in rows]


def _json_cols(row: sqlite3.Row, *cols: str) -> dict[str, Any]:
    d = dict(row)
    for c in cols:
        if d.get(c) is not None:
            d[c] = json.loads(d[c])
    return d


def _endpoint(row: sqlite3.Row) -> dict[str, Any]:
    d = _json_cols(row, "snapshot", "device_ids")
    d["manual"] = bool(d.get("manual"))
    return d


def _host(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["info"] = json.loads(d["info"]) if d.get("info") else None
    return d
