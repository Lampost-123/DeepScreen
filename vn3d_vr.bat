@echo off
rem Wrapper for vn3d_vr.ps1. Usage: vn3d_vr.bat "Window title" [divergence ^| layers]
if "%~1"=="" (
  echo Usage: vn3d_vr.bat "Window title" [divergence ^| layers]
  exit /b 1
)
if "%~2"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0vn3d_vr.ps1" -Window "%~1"
) else if /i "%~2"=="layers" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0vn3d_vr.ps1" -Window "%~1" -Layers
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0vn3d_vr.ps1" -Window "%~1" -Divergence %~2
)
