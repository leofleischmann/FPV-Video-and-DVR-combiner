@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "DOCKER_BUILDKIT=1"
set "COMPOSE_DOCKER_CLI_BUILD=1"

echo.
echo VideoDVRCombiner - Docker build ^& start
echo ========================================
echo [1] GPU Worker (NVIDIA / NVENC) — docker-compose.gpu.yml
echo     Voraussetzung: NVIDIA-Treiber + NVIDIA Container Toolkit
echo [2] Nur CPU (Standard, ohne GPU-Zugriff)
echo.
set /p PICK="Auswahl eingeben (1 oder 2): "

if "%PICK%"=="1" (
  echo.
  echo Starte mit GPU-Overlay...
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
  if errorlevel 1 exit /b 1
  goto done
)
if "%PICK%"=="2" (
  echo.
  echo Starte CPU-only...
  docker compose -f docker-compose.yml up --build -d
  if errorlevel 1 exit /b 1
  goto done
)

echo Ungueltige Auswahl. Bitte 1 oder 2.
exit /b 1

:done
echo.
echo Container laufen. Beispiele:
echo   docker compose logs -f worker
echo   docker compose ps
echo Frontend: http://localhost:8080   Backend: http://localhost:8000
endlocal
