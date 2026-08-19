#!/usr/bin/env bash
# Sync the built Parquet to S3 and register the Glue database/tables.
#
# Prereqs: build_dataset.py has already run (output/<table>/<table>.parquet
# exists for all 18 tables) and AWS credentials are live (see HANDOFF.md).
#
# Usage:
#   SOURCES_BUCKET=coa-dev-sources-data-<ACCOUNT_ID> ./load.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

: "${SOURCES_BUCKET:?set SOURCES_BUCKET to the coa-dev sources data bucket name (see HANDOFF.md)}"

GLUE_DATABASE_NAME=$(python3 -c "from schema import GLUE_DATABASE_NAME; print(GLUE_DATABASE_NAME)")
S3_PREFIX=$(python3 -c "from schema import S3_PREFIX; print(S3_PREFIX)")
TABLES=$(python3 -c "from schema import TABLES; print('\n'.join(t.name for t in TABLES))")

if [[ ! -d output ]]; then
  echo "error: output/ not found -- run 'uv run build_dataset.py' first" >&2
  exit 1
fi

echo "Regenerating Glue create-table JSON for bucket $SOURCES_BUCKET..."
SOURCES_BUCKET="$SOURCES_BUCKET" python3 glue_tables.py

echo
echo "Syncing Parquet to s3://$SOURCES_BUCKET/$S3_PREFIX/..."
while IFS= read -r table; do
  aws s3 cp "output/$table/$table.parquet" "s3://$SOURCES_BUCKET/$S3_PREFIX/$table/$table.parquet"
done <<< "$TABLES"

echo
echo "Creating Glue database $GLUE_DATABASE_NAME (skipping if it already exists)..."
if aws glue get-database --name "$GLUE_DATABASE_NAME" >/dev/null 2>&1; then
  echo "  already exists"
else
  aws glue create-database --database-input "{\"Name\":\"$GLUE_DATABASE_NAME\"}"
fi

echo
echo "Creating Glue tables..."
while IFS= read -r table; do
  if aws glue get-table --database-name "$GLUE_DATABASE_NAME" --name "$table" >/dev/null 2>&1; then
    echo "  $table: already exists, skipping (delete it first to pick up a schema change -- see plan §10 on re-scan)"
    continue
  fi
  aws glue create-table --database-name "$GLUE_DATABASE_NAME" --table-input "file://output/$table/$table-table.json"
  echo "  $table: created"
done <<< "$TABLES"

echo
echo "Done. Verify in Athena, e.g.:"
echo "  SELECT COUNT(*) FROM \"$GLUE_DATABASE_NAME\".\"holding\";"
