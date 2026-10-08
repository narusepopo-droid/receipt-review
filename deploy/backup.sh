#!/bin/bash
# 영수증리뷰 DB 백업 - 매일 새벽 (cron: /etc/cron.d/receipt-review-backup)
# - 서버 로컬 /home/ubuntu/backups 에 14일 보관
# - S3_BUCKET 이 설정되어 있고 aws CLI 가 있으면 S3 에도 업로드 (7일 보관은 S3 수명주기 규칙으로)
#
# 설치:  sudo cp deploy/backup.sh /usr/local/bin/receipt-review-backup && sudo chmod +x /usr/local/bin/receipt-review-backup
#        echo "30 4 * * * root /usr/local/bin/receipt-review-backup" | sudo tee /etc/cron.d/receipt-review-backup

set -euo pipefail

DB_NAME="${DB_NAME:-receiptreview}"
BACKUP_DIR="${BACKUP_DIR:-/home/ubuntu/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
S3_BUCKET="${S3_BUCKET:-}"
LOG_FILE="/var/log/receipt-review-backup.log"
TS=$(date +"%Y%m%d_%H%M")
FILE="${BACKUP_DIR}/${DB_NAME}_${TS}.sql.gz"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"; }

mkdir -p "$BACKUP_DIR"
log "백업 시작: $DB_NAME"

# postgres 계정 peer 인증 (비밀번호 불필요)
if sudo -u postgres pg_dump --no-owner --no-privileges "$DB_NAME" | gzip > "${FILE}.tmp"; then
    mv "${FILE}.tmp" "$FILE"
    chown ubuntu:ubuntu "$FILE" 2>/dev/null || true
    log "백업 완료: $FILE ($(du -h "$FILE" | cut -f1))"
else
    rm -f "${FILE}.tmp"
    log "오류: pg_dump 실패"
    exit 1
fi

if [[ -n "$S3_BUCKET" ]] && command -v aws >/dev/null 2>&1; then
    if aws s3 cp "$FILE" "${S3_BUCKET}/$(basename "$FILE")" --only-show-errors; then
        log "S3 업로드 완료: ${S3_BUCKET}"
    else
        log "경고: S3 업로드 실패"
    fi
fi

find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
log "오래된 백업 정리 완료 (${RETENTION_DAYS}일 초과)"
