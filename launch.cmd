@echo off
setlocal DisableDelayedExpansion
if defined TRIO_PYTHON goto explicit_python
where python >nul 2>nul
if errorlevel 1 goto try_python_launcher
python -I -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 goto python_command
:try_python_launcher
where py >nul 2>nul
if errorlevel 1 goto missing_python
py -3 -I -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 goto python_launcher
:missing_python
echo TRIO needs Python 3.11 or newer. Install Python or set TRIO_PYTHON to its executable. 1>&2
exit /b 2
:explicit_python
"%TRIO_PYTHON%" -I "%~dp0tools\launch.py" %*
exit /b %errorlevel%
:python_launcher
py -3 -I "%~dp0tools\launch.py" %*
exit /b %errorlevel%
:python_command
python -I "%~dp0tools\launch.py" %*
exit /b %errorlevel%
