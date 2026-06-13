#!/usr/bin/env bash
# Backup bazy v1 (papers_db) — uruchom PRZED migracją na postgres_v2
set -euo pipefail

CONTAINER="${1:-postgres_db}"
DB_NAME="${2:-papers_db}"
USER="${3:-admin}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/backups"
mkdir -p "$OUT_DIR"

TS="$(date +%Y%m%d_%H%M%S)"
DUMP="$OUT_DIR/${DB_NAME}_${TS}.dump"
META="$OUT_DIR/${DB_NAME}_${TS}_meta.txt"

echo "Backup $DB_NAME z $CONTAINER -> $DUMP"
docker exec "$CONTAINER" pg_dump -U "$USER" -Fc "$DB_NAME" > "$DUMP"

cat > "$META" <<EOF
backup_time=$TS
database=$DB_NAME
container=$CONTAINER
format=custom_pg_dump_Fc
note=MinIO bucket papers bez zmian
restore=docker exec -i $CONTAINER pg_restore -U $USER -d ${DB_NAME}_restore --clean $DUMP
EOF

echo "OK: $DUMP"
