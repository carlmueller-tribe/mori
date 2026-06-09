#!/usr/bin/env bash
# Run a Mori example with secrets injected from 1Password.
#
# Why: .env contains `op://...` references, not raw secret values. `op run`
# resolves those references at process start and injects them as env vars for
# the child process — secrets never touch disk.
#
# Usage:
#   examples/run-with-op.sh examples/basic_agent.py
#   examples/run-with-op.sh examples/governance.py
#   examples/run-with-op.sh examples/mori_master.py [--narrative]
#
# Requires: 1Password CLI (`op`) installed and signed in. See:
#   https://developer.1password.com/docs/cli/get-started

set -euo pipefail

if ! command -v op >/dev/null 2>&1; then
  echo "error: 1Password CLI (op) is not installed." >&2
  echo "       install: brew install 1password-cli" >&2
  exit 1
fi

# `op run` resolves any op:// references in .env, then exec's the rest.
# `--no-masking` is OFF so any accidental secret print to stdout is redacted.
exec op run --env-file=./.env -- uv run python "$@"
