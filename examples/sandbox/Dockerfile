# Sandbox image for the coding-agent experiment.
#
# Purpose: give the Mori coding agent a contained filesystem to edit and a
# bounded shell to run. The Mori source is bind-mounted read-only at runtime;
# the writable sandbox is mounted at /sandbox.
#
# Build:
#   docker build -t mori-coding-sandbox examples/sandbox/
#
# Run via the launcher (recommended):
#   examples/sandbox/run-sandbox.sh
#
# Or directly:
#   docker run --rm -it \
#     -v "$(pwd):/mori-src:ro" \
#     -v "$(mktemp -d):/sandbox" \
#     -v "$(pwd)/examples/sandbox/seed:/seed:ro" \
#     -e ANTHROPIC_API_KEY \
#     -e PYTHONPATH=/mori-src \
#     mori-coding-sandbox

FROM python:3.11-slim

# Minimal toolchain the agent's bash tool may legitimately need.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ripgrep \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Mori's runtime deps without copying source — source mounts in at
# runtime so iteration is fast. Versions pinned conservatively; the image is
# rebuilt rarely.
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
        "anthropic>=0.40" \
        "pydantic>=2.7" \
        "python-dotenv>=1.0" \
        "structlog>=24.1" \
        "pyyaml>=6.0" \
        "httpx>=0.27" \
        pytest

WORKDIR /sandbox

# Non-root user — agent shouldn't run as root inside the container.
RUN useradd --create-home --shell /bin/bash agent \
    && chown agent:agent /sandbox
USER agent

ENV PYTHONPATH=/mori-src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "/mori-src/examples/coding_sandbox.py"]
