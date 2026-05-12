#!/usr/bin/env bash
# Filesystem snapshot of kd-platform/ for the kill-switch revert layer.
# Run before any structural change. The tarball is local-only (gitignored).
#
# Usage:
#   bash scripts/snapshot.sh [label]
#
# Examples:
#   bash scripts/snapshot.sh                        # produces snapshots/snapshot-<timestamp>.tar.gz
#   bash scripts/snapshot.sh pre-nexus-integration  # produces snapshots/pre-nexus-integration-<timestamp>.tar.gz

set -euo pipefail

cd "$(dirname "$0")/.."

LABEL="${1:-snapshot}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="snapshots"
OUT_FILE="${OUT_DIR}/${LABEL}-${TIMESTAMP}.tar.gz"

mkdir -p "${OUT_DIR}"

# Exclusions:
#   snapshots/   - recursive snapshotting
#   .venv/       - virtualenv
#   pgdata/      - Postgres data dir from docker-compose
#   __pycache__  - bytecode
#   .git/        - git already serves as a second kill-switch layer
tar \
  --exclude='./snapshots' \
  --exclude='./.venv' \
  --exclude='./pgdata' \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --exclude='./.git' \
  -czf "${OUT_FILE}" \
  .

echo "Snapshot written: ${OUT_FILE}"
echo "Size: $(du -h "${OUT_FILE}" | cut -f1)"
echo ""
echo "Revert with:"
echo "  bash scripts/restore.sh ${OUT_FILE}"
