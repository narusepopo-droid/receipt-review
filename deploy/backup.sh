#!/bin/bash
# Receipt Review - Database Backup Script
# Runs daily via cron, uploads to S3, keeps 7 days of backups

set -euo pipefail

# Configuration
BACKUP_DIR="/var/backups/receipt-review"
S3_BUCKET="s3://receipt-review-backups"
RETENTION_DAYS=7
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="receipt_review_${TIMESTAMP}.sql.gz"
LOG_FILE="/var/log/receipt-review-backup.log"

# Load environment variables
if [[ -f /var/www/receipt-review/server/.env ]]; then
    export $(grep -v '^#' /var/www/receipt-review/server/.env | xargs)
fi

# Parse DATABASE_URL
# Format: postgresql://user:password@host:port/dbname
if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: DATABASE_URL not set" | tee -a "$LOG_FILE"
    exit 1
fi

# Extract database credentials from URL
DB_USER=$(echo "$DATABASE_URL" | sed -n 's|.*://\([^:]*\):.*|\1|p')
DB_PASS=$(echo "$DATABASE_URL" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p')
DB_HOST=$(echo "$DATABASE_URL" | sed -n 's|.*@\([^:]*\):.*|\1|p')
DB_PORT=$(echo "$DATABASE_URL" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
DB_NAME=$(echo "$DATABASE_URL" | sed -n 's|.*/\([^?]*\).*|\1|p')

# Create backup directory if not exists
mkdir -p "$BACKUP_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') Starting backup..." | tee -a "$LOG_FILE"

# Create database backup
PGPASSWORD="$DB_PASS" pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --format=custom \
    --compress=9 \
    --no-owner \
    --no-privileges \
    | gzip > "${BACKUP_DIR}/${BACKUP_FILE}"

if [[ $? -eq 0 ]]; then
    BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_FILE}" | cut -f1)
    echo "$(date '+%Y-%m-%d %H:%M:%S') Backup created: ${BACKUP_FILE} (${BACKUP_SIZE})" | tee -a "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: pg_dump failed" | tee -a "$LOG_FILE"
    exit 1
fi

# Upload to S3
echo "$(date '+%Y-%m-%d %H:%M:%S') Uploading to S3..." | tee -a "$LOG_FILE"
aws s3 cp "${BACKUP_DIR}/${BACKUP_FILE}" "${S3_BUCKET}/${BACKUP_FILE}" --storage-class STANDARD_IA

if [[ $? -eq 0 ]]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') Upload successful" | tee -a "$LOG_FILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: S3 upload failed" | tee -a "$LOG_FILE"
    exit 1
fi

# Clean up old local backups
echo "$(date '+%Y-%m-%d %H:%M:%S') Cleaning up old local backups..." | tee -a "$LOG_FILE"
find "$BACKUP_DIR" -name "receipt_review_*.sql.gz" -mtime +${RETENTION_DAYS} -delete

# Clean up old S3 backups
echo "$(date '+%Y-%m-%d %H:%M:%S') Cleaning up old S3 backups..." | tee -a "$LOG_FILE"
CUTOFF_DATE=$(date -d "-${RETENTION_DAYS} days" +"%Y-%m-%d")
aws s3 ls "${S3_BUCKET}/" | while read -r line; do
    FILE_DATE=$(echo "$line" | awk '{print $1}')
    FILE_NAME=$(echo "$line" | awk '{print $4}')
    if [[ "$FILE_DATE" < "$CUTOFF_DATE" ]] && [[ "$FILE_NAME" == receipt_review_*.sql.gz ]]; then
        echo "Deleting old backup: $FILE_NAME" | tee -a "$LOG_FILE"
        aws s3 rm "${S3_BUCKET}/${FILE_NAME}"
    fi
done

echo "$(date '+%Y-%m-%d %H:%M:%S') Backup completed successfully" | tee -a "$LOG_FILE"

# Optional: Send notification on success
# curl -X POST "https://hooks.slack.com/services/..." \
#     -H "Content-Type: application/json" \
#     -d "{\"text\": \"Receipt Review backup completed: ${BACKUP_FILE} (${BACKUP_SIZE})\"}"
