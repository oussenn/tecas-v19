#!/bin/bash
# Daily backup — database dump (7 days retained) + incremental filestore mirror.
#
# The filestore is not optional: it holds product images, datasheets and invoice
# attachments. Restoring a dump without it gives you a working Odoo pointing at
# files that no longer exist.
set -uo pipefail

BACKUP_DIR=/opt/tecas-v19/backups
FILESTORE_DIR="$BACKUP_DIR/filestore"
DUMP="$BACKUP_DIR/tecas19_$(date +%Y%m%d).dump"
LOG="$BACKUP_DIR/backup.log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

mkdir -p "$BACKUP_DIR" "$FILESTORE_DIR"

# --- database --------------------------------------------------------------
if ! docker exec tecas-db-19 pg_dump -U odoo19 -F c tecas19 > "$DUMP"; then
    log "ERROR: pg_dump failed — old backups kept, nothing rotated."
    rm -f "$DUMP"
    exit 1
fi

# A custom-format dump begins with "PGDMP". Anything else means a truncated or
# empty file, which must never be allowed to rotate a good backup out.
if [ ! -s "$DUMP" ] || [ "$(head -c 5 "$DUMP")" != "PGDMP" ]; then
    log "ERROR: dump is empty or not a pg_dump archive — old backups kept."
    rm -f "$DUMP"
    exit 1
fi
log "database dumped ($(du -h "$DUMP" | cut -f1))"

# --- filestore -------------------------------------------------------------
# Odoo names filestore files by content hash, so they are never rewritten in
# place: copying only what is new keeps this cheap after the first run. No
# deletion, so an attachment removed inside Odoo stays recoverable here.
if docker run --rm \
        -v tecas-v19_tecas-filestore:/src:ro \
        -v "$FILESTORE_DIR":/dst \
        alpine sh -c 'set -e; for entry in $(ls -A /src); do [ "$entry" = sessions ] || cp -au "/src/$entry" /dst/; done'; then
    # Sized inside the container: the copies are root-owned, so du on the host
    # cannot read them and would report a wrong number.
    size=$(docker run --rm -v "$FILESTORE_DIR":/dst:ro alpine du -sh /dst | cut -f1)
    log "filestore mirrored ($size, sessions excluded)"
else
    log "ERROR: filestore mirror failed — old backups kept."
    exit 1
fi

# --- rotation --------------------------------------------------------------
# Only reached when today's database dump and filestore copy both succeeded.
find "$BACKUP_DIR" -maxdepth 1 -name '*.dump' -mtime +7 -delete
log "backup complete"
