#!/usr/bin/env bash
set -euo pipefail
# Rollback experiment changes — revert all uncommitted modifications
# Preserves .research/ state files
git checkout -- . 2>/dev/null || true
git clean -fd --exclude=.research 2>/dev/null || true
echo "Rollback complete"
