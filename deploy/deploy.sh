#!/bin/bash
# Receipt Review - Deployment Script
# Usage: ./deploy.sh [--migrate] [--restart]

set -euo pipefail

# Configuration
APP_DIR="/var/www/receipt-review"
SERVICE_NAME="receipt-review"
BRANCH="main"
LOG_FILE="/var/log/receipt-review-deploy.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

log "=========================================="
log "Starting deployment..."

# Change to app directory
cd "$APP_DIR"

# Save current commit hash
PREV_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "none")
log "Current commit: $PREV_COMMIT"

# Pull latest changes
log "Pulling latest changes from $BRANCH..."
git fetch origin
git checkout $BRANCH
git pull origin $BRANCH

# Get new commit hash
NEW_COMMIT=$(git rev-parse HEAD)
log "New commit: $NEW_COMMIT"

if [[ "$PREV_COMMIT" == "$NEW_COMMIT" ]]; then
    log "No changes detected. Deployment skipped."
    exit 0
fi

# Show changes
log "Changes:"
git log --oneline ${PREV_COMMIT}..${NEW_COMMIT} | tee -a "$LOG_FILE"

# Activate virtual environment
if [[ -f "$APP_DIR/server/venv/bin/activate" ]]; then
    source "$APP_DIR/server/venv/bin/activate"
    log "Virtual environment activated"
fi

# Install dependencies
log "Installing dependencies..."
cd "$APP_DIR/server"
pip install -r requirements.txt --quiet

# Run migrations if requested or if migration files changed
if [[ "${1:-}" == "--migrate" ]] || git diff --name-only ${PREV_COMMIT}..${NEW_COMMIT} | grep -q "alembic/versions"; then
    log "Running database migrations..."
    alembic upgrade head
fi

# Restart service
log "Restarting service..."
sudo systemctl restart $SERVICE_NAME

# Wait for service to start
sleep 3

# Check service status
if systemctl is-active --quiet $SERVICE_NAME; then
    log "Service is running"
else
    log "ERROR: Service failed to start!"
    sudo systemctl status $SERVICE_NAME --no-pager | tee -a "$LOG_FILE"

    # Rollback
    log "Rolling back to previous commit..."
    cd "$APP_DIR"
    git checkout "$PREV_COMMIT"
    sudo systemctl restart $SERVICE_NAME

    exit 1
fi

# Health check
log "Running health check..."
HEALTH_URL="http://localhost:8000/health"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" || echo "000")

if [[ "$HTTP_CODE" == "200" ]]; then
    log "Health check passed"
else
    log "ERROR: Health check failed (HTTP $HTTP_CODE)"
    exit 1
fi

# Verify commit matches
DEPLOYED_COMMIT=$(git rev-parse HEAD)
if [[ "$DEPLOYED_COMMIT" == "$NEW_COMMIT" ]]; then
    log "Commit verification passed"
else
    log "ERROR: Commit mismatch!"
    exit 1
fi

log "Deployment completed successfully!"
log "=========================================="

# Show summary
echo ""
echo "Summary:"
echo "  Previous: $PREV_COMMIT"
echo "  Current:  $NEW_COMMIT"
echo "  Service:  $(systemctl is-active $SERVICE_NAME)"
echo ""
