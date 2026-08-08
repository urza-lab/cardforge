#!/bin/sh
# Back up the CardForge Postgres database and secrets to a timestamped
# archive. See BACKUP_RESTORE.md for the full procedure.
set -eu

DATA_DIR="${CARDFORGE_DATA_DIR:-./data}"
BACKUP_DIR="${DATA_DIR}/backups"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
DUMP_FILE="${BACKUP_DIR}/cardforge_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[backup] dumping Postgres database..."
docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$DUMP_FILE"

echo "[backup] database dump written to $DUMP_FILE"
echo "[backup] NOTE: back up ${DATA_DIR}/secrets separately and store it securely —"
echo "[backup]       it is required to decrypt/access nothing, but losing it means the"
echo "[backup]       app will generate NEW credentials on next start, which will NOT"
echo "[backup]       match this database dump's owning role password. Keep them together."
