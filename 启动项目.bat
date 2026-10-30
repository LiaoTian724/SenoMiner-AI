@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "SENO_CONDA_EXE="
if defined CONDA_EXE if exist "%CONDA_EXE%" set "SENO_CONDA_EXE=%CONDA_EXE%"
if not defined SENO_CONDA_EXE for /f "delims=" %%I in ('where conda.exe 2^>nul') do if not defined SENO_CONDA_EXE set "SENO_CONDA_EXE=%%I"
if not defined SENO_CONDA_EXE for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\miniforge3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%LOCALAPPDATA%\miniforge3" "%ProgramData%\miniconda3" "%ProgramData%\miniforge3" "%ProgramData%\anaconda3" "%ProgramFiles%\Miniconda3" "%ProgramFiles%\Miniforge3") do if exist "%%~D\Scripts\conda.exe" if not defined SENO_CONDA_EXE set "SENO_CONDA_EXE=%%~D\Scripts\conda.exe"
if not defined SENO_CONDA_EXE goto missing_conda
for %%I in ("%SENO_CONDA_EXE%") do set "SENO_CONDA_DIR=%%~dpI"
set "SENO_BASE_PYTHON=%SENO_CONDA_DIR%..\python.exe"
if not exist "%SENO_BASE_PYTHON%" set "SENO_BASE_PYTHON=%SENO_CONDA_DIR%python.exe"
if not exist "%SENO_BASE_PYTHON%" goto missing_conda
"%SENO_BASE_PYTHON%" "%~dp0tools\windows_launcher.py" --conda "%SENO_CONDA_EXE%"
set "SENO_EXIT=%ERRORLEVEL%"
if not "%SENO_EXIT%"=="0" pause
endlocal & exit /b %SENO_EXIT%
:missing_conda
echo Miniconda or Miniforge for Windows x64 was not found.
echo Install it once, then double-click this file again.
echo Official installer: https://github.com/conda-forge/miniforge#download
pause
endlocal & exit /b 1
