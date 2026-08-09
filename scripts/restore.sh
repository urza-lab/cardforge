#!/bin/sh
# Restore a CardForge Postgres backup created by scripts/backup.sh.
# Usage: scripts/restore.sh path/to/cardforge_TIMESTAMP.sql.gz
set -eu

if [ $# -ne 1 ]; then
  echo "Usage: $0 <backup-file.sql.gz>" >&2
  exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

echo "[restore] WARNING: this will overwrite the current database contents."
printf "[restore] type 'yes' to continue: "
read -r CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "[restore] aborted"
  exit 1
fi

echo "[restore] restoring from $BACKUP_FILE ..."
gunzip -c "$BACKUP_FILE" | docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

echo "[restore] done. Restart the backend to ensure it reconnects cleanly:"
echo "[restore]   docker compose restart backend worker"
