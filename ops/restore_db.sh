#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 /path/to/backup.db" >&2
  exit 1
fi

BACKUP_PATH="$1"
DB_PATH="${MEMORY_DB_PATH:-/Users/rodolfo/Developer/memory/data/memory.db}"
DB_DIR="$(dirname "$DB_PATH")"

if [ ! -f "$BACKUP_PATH" ]; then
  echo "backup file not found: $BACKUP_PATH" >&2
  exit 1
fi

mkdir -p "$DB_DIR"
cp "$BACKUP_PATH" "$DB_PATH"
rm -f "$DB_PATH-wal" "$DB_PATH-shm"

echo "restored $DB_PATH from $BACKUP_PATH"
