@echo off
setlocal EnableExtensions
title Wander - offline AI, anywhere
chcp 65001 >nul
cd /d "%~dp0"

set "WANDER_HOME=%~dp0data"
set "WANDER_MODELS=%~dp0models"
set "TMPDIR=%~dp0data\.tmp"
set "TEMP=%~dp0data\.tmp"
set "TMP=%~dp0data\.tmp"
set "HF_HOME=%~dp0data\.cache\hf"
set "PIP_CACHE_DIR=%~dp0data\.cache\pip"
set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "HF_HUB_OFFLINE=1"
set "TRANSFORMERS_OFFLINE=1"
set "PYDIR=%~dp0runtime"

mkdir "%~dp0data\.tmp" 2>nul

if not exist "%PYDIR%\engine.ready" (
  call "%~dp0INSTALL.bat" auto
)

if not exist "%PYDIR%\engine.ready" (
  echo   Engine setup incomplete. Run INSTALL.bat first.
  pause
  exit /b
)

"%PYDIR%\python.exe" -B "%~dp0wander.py" %*
if errorlevel 1 pause
exit /b
