@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "DOCKER_BUILDKIT=1"
set "COMPOSE_DOCKER_CLI_BUILD=1"

echo.
echo VideoDVRCombiner - Docker build ^& start
echo ========================================
echo [1] GPU worker (NVIDIA / NVENC) — docker-compose.gpu.yml
echo     Requires: NVIDIA driver + NVIDIA Container Toolkit
echo [2] CPU only (default, no GPU)
echo.
set /p PICK="Choose (1 or 2): "

if "%PICK%"=="1" (
  echo.
  echo Starting with GPU overlay...
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
  if errorlevel 1 exit /b 1
  goto done
)
if "%PICK%"=="2" (
  echo.
  echo Starting CPU-only...
  docker compose -f docker-compose.yml up --build -d
  if errorlevel 1 exit /b 1
  goto done
)

echo Invalid choice. Enter 1 or 2.
exit /b 1

:done
echo.
echo Containers running. Examples:
echo   docker compose logs -f worker
echo   docker compose ps
echo Frontend: http://localhost:8080   Backend: http://localhost:8000
endlocal
