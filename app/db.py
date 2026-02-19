from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA busy_timeout=5000;")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    try:
        conn.execute("BEGIN")
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def run_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    if not migrations_dir.exists():
        raise FileNotFoundError(f"migrations directory does not exist: {migrations_dir}")

    row = conn.execute("PRAGMA user_version;").fetchone()
    current = int(row[0]) if row is not None else 0

    migrations = []
    for path in sorted(migrations_dir.glob("*.sql")):
        prefix = path.stem.split("_", 1)[0]
        if not prefix.isdigit():
            continue
        migrations.append((int(prefix), path))

    for version, path in migrations:
        if version <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        with transaction(conn):
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version={version};")
        current = version
