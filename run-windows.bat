@echo off
REM GoFindMe launcher for Windows (requires Python 3.11+ installed).
REM For a no-Python option, download the packaged GoFindMe-windows.exe from the
REM repository's "desktop-latest" GitHub release instead.
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if exist ".git" (
  where git >nul 2>nul && (
    echo Checking for updates...
    git pull --ff-only
  )
)

if not exist ".venv\Scripts\activate.bat" (
  echo Creating virtual environment...
  %PY% -m venv .venv
)
call ".venv\Scripts\activate.bat"

echo Installing dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt || goto :error

echo.
echo GoFindMe starting at http://127.0.0.1:8000  (close this window to stop)
start "" http://127.0.0.1:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:error
echo.
echo Setup failed. If this was a network error, check your internet/proxy and retry.
pause
