@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "root=%~dp0"
set "app=%root%tools\live_hd.py"
set "archive=%root%inputs\reference.zip"
set "core=%root%inputs\dosbox_pure_libretro.dll"
set "runs=%root%data\runs"
set "profile=%root%data\profile"

for %%I in ("%app%" "%archive%" "%core%") do (
  if not exist "%%~fI" (
    >&2 echo Missing SimAnt file: "%%~fI"
    goto setup_error
  )
)

set "python=%root%runtime\python.exe"
if exist "%python%" goto check_python
set "python=%SIMANT_PYTHON%"
if defined python goto check_python
for %%I in (python.exe) do set "python=%%~$PATH:I"

:check_python
if not defined python goto python_error
if not exist "%python%" goto python_error
"%python%" -I -B -c "import sys, sysconfig, tkinter; sys.exit(0 if sys.version_info >= (3, 11) and sysconfig.get_platform() == 'win-amd64' else 1)" >nul 2>&1
if errorlevel 1 goto python_error

if not exist "%runs%\" mkdir "%runs%"
if not exist "%runs%\" goto setup_error
:choose_session
set "session=%runs%\session-%RANDOM%-%RANDOM%"
if exist "%session%" goto choose_session
"%python%" -E -s -B "%app%" --archive "%archive%" --core "%core%" --out "%session%" --save-dir "%profile%"
set "result=%ERRORLEVEL%"
if not "%result%"=="0" pause
exit /b %result%

:python_error
>&2 echo SimAnt requires Python 3.11 or later for Windows x64 with Tk.
>&2 echo Put it in the runtime folder or set SIMANT_PYTHON to the full python.exe path.
:setup_error
pause
exit /b 1
