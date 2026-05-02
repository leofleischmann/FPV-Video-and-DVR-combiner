#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

echo ""
echo "VideoDVRCombiner - Docker build & start"
echo "========================================"
echo "[1] GPU worker (NVIDIA / NVENC) — docker-compose.gpu.yml"
echo "    Requires: NVIDIA driver + NVIDIA Container Toolkit"
echo "[2] CPU only (default, no GPU)"
echo ""
read -r -p "Choose (1 or 2): " PICK

case "${PICK}" in
  1)
    echo ""
    echo "Starting with GPU overlay..."
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
    ;;
  2)
    echo ""
    echo "Starting CPU-only..."
    docker compose -f docker-compose.yml up --build -d
    ;;
  *)
    echo "Invalid choice. Enter 1 or 2." >&2
    exit 1
    ;;
esac

echo ""
echo "Containers running. Examples:"
echo "  docker compose logs -f worker"
echo "  docker compose ps"
echo "Frontend: http://localhost:8080   Backend: http://localhost:8000"
