@echo off
setlocal EnableExtensions
title Wander Installer
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
set "PYDIR=%~dp0runtime"
set "PYVER=3.12.7"

mkdir "%~dp0data\.tmp" 2>nul

rem ---- silent full install (called by START-WANDER.bat) ----
if /i "%~1"=="auto" (
  call :install_all
  exit /b
)

:menu
cls
echo.
echo   WANDER INSTALLER
echo.
if exist "%PYDIR%\engine.ready" (
  echo   Base engine: installed
) else (
  echo   Base engine: not installed
)
echo.
echo   1. Base engine
echo   2. Turbo engine
echo   3. GPU engine (NVIDIA)
echo   4. Everything (base + turbo + GPU)   [no prompts]
echo   5. Exit
echo.
set "CHOICE="
set /p CHOICE="  Option: "
if "%CHOICE%"=="1" call :install_base
if "%CHOICE%"=="2" call :install_turbo
if "%CHOICE%"=="3" call :install_gpu
if "%CHOICE%"=="4" call :install_all
if "%CHOICE%"=="5" exit /b
echo.
pause
goto menu

:install_base
echo.
echo   Installing base engine...
echo   [1/4] Python runtime
call :download "https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-amd64.zip" "%~dp0pyembed.zip"
if errorlevel 1 goto fail
mkdir "%PYDIR%" 2>nul
tar -xf "%~dp0pyembed.zip" -C "%PYDIR%" 2>nul
if not exist "%PYDIR%\python.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%~dp0pyembed.zip' -DestinationPath '%PYDIR%' -Force"
)
del "%~dp0pyembed.zip" 2>nul
if not exist "%PYDIR%\python.exe" goto fail
> "%PYDIR%\python312._pth" (
echo python312.zip
echo .
echo Lib\site-packages
echo import site
)
echo   [2/4] package manager
call :download "https://bootstrap.pypa.io/get-pip.py" "%PYDIR%\get-pip.py"
if errorlevel 1 goto fail
"%PYDIR%\python.exe" "%PYDIR%\get-pip.py" --no-compile --no-warn-script-location >nul
if errorlevel 1 goto fail
echo   [3/4] PyTorch
"%PYDIR%\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cpu --no-compile --no-warn-script-location
if errorlevel 1 goto fail
echo   [4/4] components
"%PYDIR%\python.exe" -m pip install transformers accelerate sentencepiece gguf rich prompt_toolkit --no-compile --no-warn-script-location
if errorlevel 1 goto fail
echo ready > "%PYDIR%\engine.ready"
echo   Done.
echo.
exit /b

:install_turbo
echo.
if not exist "%PYDIR%\python.exe" (
  echo   Install the base engine first.
  exit /b
)
echo   Installing turbo engine...
"%PYDIR%\python.exe" -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --no-compile --no-warn-script-location
if errorlevel 1 goto fail
echo   Done.
echo.
exit /b

:install_gpu
echo.
if not exist "%PYDIR%\python.exe" (
  echo   Install the base engine first.
  exit /b
)
set "CU="
for /f "delims=" %%v in ('"%PYDIR%\python.exe" -c "import subprocess,re,shutil;o=subprocess.run(['nvidia-smi'],capture_output=True,text=True).stdout if shutil.which('nvidia-smi') else '';m=re.search(r'CUDA Version: (\d+)\.(\d+)',o);print('cu124' if m and (int(m.group(1)),int(m.group(2)))>=(12,4) else 'cu121' if m and (int(m.group(1)),int(m.group(2)))>=(12,1) else '')" 2^>nul') do set "CU=%%v"
if "%CU%"=="" (
  echo   No NVIDIA GPU/driver found ^(needs CUDA 12.1+^) - will use CPU.
  exit /b
)
echo   NVIDIA GPU detected - installing GPU engine (%CU%)...
"%PYDIR%\python.exe" -m pip install llama-cpp-python --force-reinstall --only-binary :all: --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/%CU% --no-compile --no-warn-script-location
if errorlevel 1 (
  echo   GPU engine skipped ^(no matching prebuilt wheel^) - will use CPU.
) else (
  echo   Done.
)
echo.
exit /b

:install_all
call :install_base
if not exist "%PYDIR%\engine.ready" goto fail
call :install_turbo
call :install_gpu
echo   All done.
echo.
exit /b

:download
curl -L --fail --retry 2 -o "%~2" "%~1"
if not errorlevel 1 exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%~1' -OutFile '%~2'"
if not errorlevel 1 exit /b 0
exit /b 1

:fail
echo.
echo   Download failed. Check your connection and run again.
echo.
exit /b
