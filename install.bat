@echo off
setlocal
pushd "%~dp0"

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv || goto :error
)

echo Installing dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip || goto :error
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error

echo.
echo Done. Run .\run.bat to start TokenWatcher.
popd
exit /b 0

:error
echo.
echo Install failed.
popd
exit /b 1
