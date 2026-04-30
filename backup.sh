#!/bin/bash
# Daily DB backup — keeps last 7 days
BACKUP_DIR=/opt/tecas-v19/backups
mkdir -p $BACKUP_DIR
docker exec tecas-db-19 pg_dump -U odoo19 -F c tecas19 > $BACKUP_DIR/tecas19_$(date +%Y%m%d).dump
# Delete backups older than 7 days
find $BACKUP_DIR -name "*.dump" -mtime +7 -delete
