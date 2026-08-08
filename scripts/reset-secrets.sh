#!/bin/sh
# Deliberately rotate one or more CardForge persistent secrets.
#
# This is destructive for db_password: rotating it WITHOUT also updating the
# password of the existing Postgres role will lock the backend out of its own
# database. Prefer rotating app_secret_key or grafana_admin_password alone
# unless you know you also need an `ALTER ROLE ... PASSWORD` step in Postgres.
#
# Usage: scripts/reset-secrets.sh <db_password|app_secret_key|grafana_admin_password|all>
set -eu

DATA_DIR="${CARDFORGE_DATA_DIR:-./data}"
SECRETS_DIR="${DATA_DIR}/secrets"

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "Usage: $0 <db_password|app_secret_key|grafana_admin_password|all>" >&2
  exit 1
fi

confirm() {
  printf "[reset-secrets] This permanently deletes %s. Type 'yes' to continue: " "$1"
  read -r CONFIRM
  [ "$CONFIRM" = "yes" ]
}

remove_one() {
  file="${SECRETS_DIR}/$1"
  if [ -f "$file" ]; then
    if confirm "$1"; then
      rm -f "$file"
      echo "[reset-secrets] removed $1 — a new value will be generated on next 'docker compose up' (or taken from the matching env var, if set)"
    else
      echo "[reset-secrets] skipped $1"
    fi
  else
    echo "[reset-secrets] $1 does not exist, nothing to do"
  fi
}

case "$TARGET" in
  db_password|app_secret_key|grafana_admin_password)
    remove_one "$TARGET"
    ;;
  all)
    remove_one db_password
    remove_one app_secret_key
    remove_one grafana_admin_password
    ;;
  *)
    echo "Unknown target: $TARGET" >&2
    exit 1
    ;;
esac
