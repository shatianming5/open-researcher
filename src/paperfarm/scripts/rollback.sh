#!/usr/bin/env bash
# Rollback the last experiment commit (git reset --hard HEAD~1).
# Used by the agent when an experiment doesn't improve the primary metric.
set -Eeuo pipefail

echo "[rollback] Resetting to previous commit..."
git reset --hard HEAD~1
echo "[OK] Rolled back to $(git rev-parse --short=7 HEAD)"
