#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${MEMORY_DB_PATH:-/Users/rodolfo/Developer/memory/data/memory.db}"
BACKUP_DIR="${MEMORY_BACKUP_DIR:-/Users/rodolfo/Developer/memory/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/memory_$STAMP.db"

mkdir -p "$BACKUP_DIR"

if command -v sqlite3 >/dev/null 2>&1 && [ -f "$DB_PATH" ]; then
  sqlite3 "$DB_PATH" "PRAGMA wal_checkpoint(FULL);" >/dev/null
  sqlite3 "$DB_PATH" ".backup '$OUT'"
else
  cp "$DB_PATH" "$OUT"
fi

echo "$OUT"
