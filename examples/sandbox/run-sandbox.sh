#!/usr/bin/env bash
# Launch the Mori coding-agent experiment inside the sandbox container.
#
# Layout inside the container:
#   /mori-src        — this repo (read-only bind mount)
#   /seed            — seed project (read-only bind mount)
#   /sandbox         — writable scratch (tmp dir on host)
#   /sandbox/project — where the agent's tools may read/write
#   /sandbox/audit.jsonl — observability output, copied back to host on exit
#
# The ANTHROPIC_API_KEY is resolved on the host via 1Password (`op run`) and
# passed to the container as an env var. The key never appears on disk.
#
# Usage:
#   examples/sandbox/run-sandbox.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRATCH="$(mktemp -d -t mori-sandbox-XXXXXX)"
IMAGE="mori-coding-sandbox"

# Seed the sandbox project from the seed dir.
mkdir -p "$SCRATCH/project"
cp -r "$REPO_ROOT/examples/sandbox/seed/." "$SCRATCH/project/"
echo "==> Sandbox scratch dir: $SCRATCH"

# Build the image (cached after first build).
echo "==> Building image $IMAGE..."
docker build -t "$IMAGE" -f "$REPO_ROOT/examples/sandbox/Dockerfile" "$REPO_ROOT/examples/sandbox/" >/dev/null

# Resolve the API key via 1Password and run.
echo "==> Launching agent in container..."
op run --env-file="$REPO_ROOT/.env" -- \
  docker run --rm \
    --name "mori-coding-sandbox-$$" \
    -v "$REPO_ROOT:/mori-src:ro" \
    -v "$SCRATCH:/sandbox" \
    -v "$REPO_ROOT/examples/sandbox/seed:/seed:ro" \
    -e ANTHROPIC_API_KEY \
    -e MORI_SANDBOX_MODE \
    -e MORI_SANDBOX_MODEL \
    "$IMAGE"

echo
echo "==> Agent exited. Sandbox preserved at: $SCRATCH"
echo "    audit trail:     $SCRATCH/audit.jsonl"
echo "    project changes: $SCRATCH/project/"
echo
echo "    Inspect:"
echo "      cat $SCRATCH/audit.jsonl | jq '.event_type' | sort | uniq -c"
echo "      diff -ru $REPO_ROOT/examples/sandbox/seed/ $SCRATCH/project/"
