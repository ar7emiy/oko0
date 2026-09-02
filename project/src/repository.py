"""Thin repository layer over SQLite (+ parquet for bulk tables).

Storage is wrapped so a future SQL Server swap is mechanical: callers use the
Repository methods, never raw SQL scattered across notebooks. Mentions and
assertions are immutable by convention (insert-only; no UPDATE/DELETE). Entity
membership changes are new rows in entity_versions / entity_members.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pandas as pd

from . import contracts
from .settings import Paths


class Repository:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or Paths.db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    # ---- lifecycle ---------------------------------------------------------
    def init_schema(self) -> None:
        self.conn.executescript(contracts.DDL)
        self.conn.commit()
        self._migrate_added_columns()

    def _migrate_added_columns(self) -> None:
        """Add columns the DDL declares that an existing table is missing.

        CREATE TABLE IF NOT EXISTS is a no-op on a table that already exists, so
        adding a column to contracts.DDL leaves every existing database silently
        behind -- the next insert fails with "table X has no column named Y", and
        the only remedy was a full reset. On this corpus that is an 11-minute
        re-extraction to pick up one column, which in practice discourages
        schema changes that ought to be cheap.

        Deliberately narrow: it only ADDS columns. It never drops, renames or
        retypes, because each of those loses data and should be an explicit,
        reviewed migration rather than something that happens on connect.
        """
        want = self._declared_columns()
        cur = self.conn.cursor()
        added = []
        for table, cols in want.items():
            try:
                have = {r["name"] for r in
                        cur.execute(f"PRAGMA table_info({table})").fetchall()}
            except sqlite3.Error:
                continue
            if not have:
                continue                      # table not created yet
            for name, decl in cols.items():
                if name not in have:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                    added.append(f"{table}.{name}")
        if added:
            self.conn.commit()
        self.migrations_applied = added

    @staticmethod
    def _declared_columns() -> dict:
        """{table: {column: type-and-default}} parsed from contracts.DDL."""
        out = {}
        pattern = r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);"
        for m in re.finditer(pattern, contracts.DDL, re.S):
            table, body = m.group(1), m.group(2)
            cols = {}
            for line in body.splitlines():
                line = line.split("--")[0].strip().rstrip(",")
                if not line or line.upper().startswith(
                        ("FOREIGN KEY", "PRIMARY KEY", "UNIQUE", "CHECK")):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                name, decl = parts[0], " ".join(parts[1:])
                # ALTER TABLE ADD COLUMN cannot add a PRIMARY KEY or a UNIQUE
                # column, and an existing table already has its key anyway.
                if "PRIMARY KEY" in decl.upper() or "UNIQUE" in decl.upper():
                    continue
                cols[name] = decl
            out[table] = cols
        return out

    def reset(self) -> None:
        """Drop all known tables and recreate. Used at the top of a fresh run."""
        cur = self.conn.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        for t in contracts.TABLE_NAMES:
            cur.execute(f"DROP TABLE IF EXISTS {t}")
        self.conn.commit()
        cur.execute("PRAGMA foreign_keys=ON")
        self.init_schema()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- generic insert ----------------------------------------------------
    def _insert(self, table: str, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        cols = list(rows[0].keys())
        ph = ",".join("?" for _ in cols)
        sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})"
        self.conn.executemany(sql, [[r.get(c) for c in cols] for r in rows])
        self.conn.commit()
        return len(rows)

    @staticmethod
    def _as_dicts(items) -> list[dict]:
        out = []
        for it in items:
            out.append(asdict(it) if is_dataclass(it) else dict(it))
        return out

    # ---- typed inserts -----------------------------------------------------
    def add_documents(self, rows) -> int:
        return self._insert("documents", self._as_dicts(rows))

    def add_segments(self, rows) -> int:
        return self._insert("segments", self._as_dicts(rows))

    def add_mentions(self, rows) -> int:
        return self._insert("mentions", self._as_dicts(rows))

    def add_assertions(self, rows) -> int:
        return self._insert("assertions", self._as_dicts(rows))

    def add_same_as_edges(self, rows) -> int:
        return self._insert("same_as_edges", self._as_dicts(rows))

    def add_entity_snapshot(self, rows) -> int:
        return self._insert("entity_snapshot", self._as_dicts(rows))

    def add_identifier_observations(self, rows) -> int:
        return self._insert("identifier_observations", self._as_dicts(rows))

    def add_coref_links(self, rows) -> int:
        return self._insert("coref_links", self._as_dicts(rows))

    def add_scan_spans(self, rows) -> int:
        return self._insert("scan_ledger", self._as_dicts(rows))

    def add_entities(self, rows) -> int:
        return self._insert("entities", self._as_dicts(rows))

    def add_entity_members(self, rows) -> int:
        return self._insert("entity_members", self._as_dicts(rows))

    def add_entity_versions(self, rows) -> int:
        return self._insert("entity_versions", self._as_dicts(rows))

    def add_entity_attributes(self, rows) -> int:
        return self._insert("entity_attributes", self._as_dicts(rows))

    def upsert_dossier(self, entity_id: str, dossier: dict) -> None:
        self.conn.execute(
            "INSERT INTO dossiers(entity_id, dossier_json) VALUES(?,?) "
            "ON CONFLICT(entity_id) DO UPDATE SET dossier_json=excluded.dossier_json",
            (entity_id, json.dumps(dossier)),
        )
        self.conn.commit()

    # ---- reads -------------------------------------------------------------
    def df(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        return pd.read_sql_query(sql, self.conn, params=params)

    def table(self, name: str) -> pd.DataFrame:
        return self.df(f"SELECT * FROM {name}")

    def get_dossier(self, entity_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT dossier_json FROM dossiers WHERE entity_id=?", (entity_id,)
        ).fetchone()
        return json.loads(row["dossier_json"]) if row else None

    def all_dossiers(self) -> list[dict]:
        rows = self.conn.execute("SELECT dossier_json FROM dossiers").fetchall()
        return [json.loads(r["dossier_json"]) for r in rows]

    # ---- parquet bulk dump (bulk tables) ----------------------------------
    def dump_parquet(self, tables: Iterable[str] | None = None) -> list[Path]:
        tables = list(tables or ("documents", "segments", "mentions", "assertions",
                                 "scan_ledger", "entity_attributes"))
        out = []
        for t in tables:
            df = self.table(t)
            p = Paths.store / f"{t}.parquet"
            df.to_parquet(p, index=False)
            out.append(p)
        return out
