@echo off
rem ============================================================
rem  V6PAC - VOCALOID6 splash screen replacer
rem  Double-click this file to start.
rem  (ASCII only on purpose: cmd.exe mis-parses UTF-8 comments)
rem ============================================================

setlocal
set "HERE=%~dp0"
set "SCRIPT=%HERE%V6PAC.py"

if not exist "%SCRIPT%" (
    echo.
    echo   [ERROR] V6PAC.py not found
    echo   Expected: %SCRIPT%
    echo.
    pause
    exit /b 1
)

rem ------------------------------------------------------------
rem  Find a Python that ACTUALLY RUNS.
rem
rem  Two traps this guards against:
rem
rem  1) A zero-byte App Execution Alias at
rem       %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe
rem     is on PATH by default on Windows 10/11. `where` finds it, it is
rem     not a real interpreter, and running it exits 9009. Every candidate
rem     is therefore probed with "import sys" and only a success is taken.
rem
rem  2) PY and PYARG are kept SEPARATE. The py launcher needs "-3", but
rem     storing "py.exe -3" in one variable and writing "%PY%" "%SCRIPT%"
rem     makes cmd treat "py.exe -3" as a single quoted path -> 9009.
rem     The launcher's extra argument lives in PYARG and is passed unquoted.
rem ------------------------------------------------------------
set "PY="
set "PYARG="

call :try "%HERE%python\python.exe"
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
if not defined PY call :try "C:\Program Files\Python313\python.exe"
if not defined PY call :try "C:\Program Files\Python312\python.exe"
if not defined PY call :try "C:\Program Files\Python311\python.exe"
if not defined PY call :try "C:\Program Files\Python310\python.exe"
if not defined PY call :try "C:\Program Files\Python39\python.exe"
if not defined PY call :try "D:\Program Files\python\python.exe"

rem The py launcher, if present and working. Skipped when it is the store stub.
if not defined PY (
    for /f "delims=" %%i in ('where py.exe 2^>nul') do (
        if not defined PY call :trylauncher "%%i"
    )
)

rem Last resort: whatever PATH resolves to - still probed, so the
rem WindowsApps alias is rejected here too.
if not defined PY (
    for /f "delims=" %%i in ('where python.exe 2^>nul') do (
        if not defined PY call :try "%%i"
    )
)

if not defined PY (
    echo.
    echo   [ERROR] No working Python found.
    echo.
    echo   The usual cause is a "python.exe" that is really the Microsoft
    echo   Store placeholder: running it exits with code 9009.
    echo.
    echo   Fix it in one of these ways:
    echo     1^) Install Python 3.9+ from https://www.python.org/downloads/
    echo        and TICK "Add python.exe to PATH" during setup.
    echo     2^) Put a real python.exe in: "%HERE%python\python.exe"
    echo.
    echo   Check what Windows thinks you have:   where python
    echo.
    pause
    exit /b 1
)

rem Show the argument with a space so "py.exe -3" does not print as "py.exe-3".
set "PYSHOW=%PY%"
if defined PYARG set "PYSHOW=%PY% %PYARG%"
echo   Python : %PYSHOW%

rem ------------------------------------------------------------
rem  Dependency check BEFORE launching, with an offer to fix it.
rem
rem  A missing Pillow used to surface as a Python traceback followed by
rem  exit code 1, which is correct but leaves the user to work out the
rem  install command themselves. Probing here means we can say exactly
rem  what is missing and offer to install it on the spot.
rem ------------------------------------------------------------
"%PY%" %PYARG% -c "import PIL" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [MISSING] Pillow is not installed for this Python.
    echo             It is required for image scaling and preview.
    echo.
    echo   Install it now? This runs:
    echo       %PYSHOW% -m pip install pillow
    echo.
    choice /c YN /n /m "   Proceed? [Y/N] "
    if errorlevel 2 (
        echo.
        echo   Skipped. Install it manually, then run this launcher again:
        echo       %PYSHOW% -m pip install pillow
        echo.
        pause
        exit /b 1
    )
    echo.
    "%PY%" %PYARG% -m pip install pillow
    if errorlevel 1 (
        echo.
        echo   [ERROR] pip install failed. Common causes:
        echo     - no internet access
        echo     - pip itself is missing:  %PYSHOW% -m ensurepip
        echo     - behind a proxy, add:    --proxy http://host:port
        echo.
        pause
        exit /b 1
    )
    echo.
    echo   Pillow installed.
    echo.
)

rem tkinter cannot be pip-installed; check it too so the error is actionable.
"%PY%" %PYARG% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [MISSING] tkinter is not available for this Python.
    echo             It is the GUI toolkit and CANNOT be installed with pip.
    echo.
    echo   Fix: re-run the Python installer ^> Modify, then tick
    echo        "tcl/tk and IDLE", and finish the setup.
    echo.
    pause
    exit /b 1
)

echo   Starting V6PAC ...
echo.

rem PYARG is intentionally unquoted (it is empty or a bare switch like -3).
"%PY%" %PYARG% "%SCRIPT%"
set "RC=%ERRORLEVEL%"

if %RC% neq 0 (
    echo.
    echo   Exited with code %RC%
    pause
)
endlocal
exit /b 0

rem ------------------------------------------------------------
:try
rem %~1 = candidate path. Accept only if it exists AND runs.
if defined PY goto :eof
if not exist "%~1" goto :eof
"%~1" -c "import sys" >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%~1"
goto :eof

:trylauncher
rem %~1 = path to py.exe. Needs -3 to select Python 3; the switch is
rem recorded separately in PYARG so it is never folded into the path.
if defined PY goto :eof
if not exist "%~1" goto :eof
"%~1" -3 -c "import sys" >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%~1"
set "PYARG=-3"
goto :eof
