#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

echo "=== UV Sync (Locked) ==="
uv sync --locked

echo "=== Ruff Check ==="
uv run ruff check .

echo "=== Ruff Format Check ==="
uv run ruff format --check .

echo "=== Pytest ==="
uv run pytest
