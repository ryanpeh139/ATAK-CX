#!/usr/bin/env bash
# Back up everything needed to rebuild the server without re-onboarding anyone:
# the certificate authority, OpenTAKServer's config, uploads and database, and
# ~/takcx (team settings + everyone's packages).
#
#   ./setup/backup.sh [backup-dir]      default: ~/takcx-backups, keeps 14
#
# Restore steps are in docs/maintenance.md. Copy backups off the server
# regularly: they contain the keys to your whole setup, so keep them private.
set -euo pipefail

OTS_DIR="${OTS_DATA_FOLDER:-$HOME/ots}"
TAKCX_HOME="${TAKCX_HOME:-$HOME/takcx}"
BACKUP_DIR="${1:-$HOME/takcx-backups}"
KEEP=14

stamp="$(date +%Y%m%d-%H%M%S)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Database login comes from OpenTAKServer's own config.
db_uri="$(sed -n 's/^SQLALCHEMY_DATABASE_URI: *//p' "$OTS_DIR/config.yml" | tr -d "'\"")"
if [[ $db_uri =~ ^postgresql[^:]*://([^:]+):(.*)@([^/@]+)/([^/?]+)$ ]]; then
  PGPASSWORD="${BASH_REMATCH[2]}" pg_dump -h "${BASH_REMATCH[3]%%:*}" -U "${BASH_REMATCH[1]}" \
    --no-owner "${BASH_REMATCH[4]}" > "$work/ots.sql"
else
  echo "Warning: couldn't read the database settings, skipping the database dump." >&2
fi

items=(-C "$(dirname "$OTS_DIR")" "$(basename "$OTS_DIR")/ca" "$(basename "$OTS_DIR")/config.yml")
[[ -d $OTS_DIR/uploads ]] && items+=("$(basename "$OTS_DIR")/uploads")
items+=(-C "$(dirname "$TAKCX_HOME")" "$(basename "$TAKCX_HOME")")
[[ -f $work/ots.sql ]] && items+=(-C "$work" ots.sql)

archive="$BACKUP_DIR/takcx-backup-$stamp.tar.gz"
tar --exclude="*.log" -czf "$archive" "${items[@]}"
chmod 600 "$archive"

# Drop the oldest ones beyond $KEEP.
# shellcheck disable=SC2012  # names are ours and space-free
ls -1t "$BACKUP_DIR"/takcx-backup-*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "Backup saved: $archive ($(du -h "$archive" | cut -f1))"
