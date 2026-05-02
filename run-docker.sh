#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

echo ""
echo "VideoDVRCombiner - Docker build & start"
echo "========================================"
echo "[1] GPU Worker (NVIDIA / NVENC) — docker-compose.gpu.yml"
echo "    Voraussetzung: NVIDIA-Treiber + NVIDIA Container Toolkit"
echo "[2] Nur CPU (Standard, ohne GPU-Zugriff)"
echo ""
read -r -p "Auswahl eingeben (1 oder 2): " PICK

case "${PICK}" in
  1)
    echo ""
    echo "Starte mit GPU-Overlay..."
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
    ;;
  2)
    echo ""
    echo "Starte CPU-only..."
    docker compose -f docker-compose.yml up --build -d
    ;;
  *)
    echo "Ungültige Auswahl. Bitte 1 oder 2." >&2
    exit 1
    ;;
esac

echo ""
echo "Container laufen. Beispiele:"
echo "  docker compose logs -f worker"
echo "  docker compose ps"
echo "Frontend: http://localhost:8080   Backend: http://localhost:8000"
