#!/usr/bin/env bash
# Restore kd-platform/ from a snapshot tarball.
# This is the nuclear-revert layer of the kill switch — it overwrites all
# non-gitignored files with the snapshot contents.
#
# Usage:
#   bash scripts/restore.sh snapshots/pre-nexus-integration-<timestamp>.tar.gz
#
# The script:
#   1. Refuses to run if working tree has uncommitted changes (use git stash first)
#   2. Removes all files matching the snapshot's contents (excluding .git, snapshots/, .venv/)
#   3. Extracts the snapshot in place
#   4. Reminds you to `git status` to verify the working tree state

set -euo pipefail

cd "$(dirname "$0")/.."

if [ "$#" -ne 1 ]; then
  echo "Usage: bash scripts/restore.sh <snapshot.tar.gz>"
  echo ""
  echo "Available snapshots:"
  ls -lh snapshots/*.tar.gz 2>/dev/null || echo "  (none)"
  exit 1
fi

SNAPSHOT="$1"

if [ ! -f "${SNAPSHOT}" ]; then
  echo "Error: snapshot not found: ${SNAPSHOT}"
  exit 1
fi

if [ -d .git ]; then
  if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    echo "Error: working tree has uncommitted changes."
    echo "  git stash push -u   # save them"
    echo "  # ...then rerun this script."
    exit 1
  fi
fi

echo "About to restore from: ${SNAPSHOT}"
echo "This will overwrite the current kd-platform/ tree (excluding .git, snapshots/, .venv/)."
read -r -p "Proceed? [y/N] " confirm
if [[ ! "${confirm}" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 1
fi

# Wipe top-level tracked content but preserve .git, snapshots/, .venv/
find . -maxdepth 1 \
  ! -name '.' \
  ! -name '.git' \
  ! -name 'snapshots' \
  ! -name '.venv' \
  -exec rm -rf {} +

tar -xzf "${SNAPSHOT}" -C .

echo ""
echo "Restore complete."
echo "Verify with: git status"
