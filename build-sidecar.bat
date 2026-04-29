@echo off
echo Building Claude sidecar (claude_fetch.exe)...

pip install -r sidecar\requirements.txt pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: pip install failed
    exit /b 1
)

pyinstaller --onefile --name claude_fetch --distpath resources --noconfirm sidecar\claude_fetch.py
if errorlevel 1 (
    echo ERROR: PyInstaller failed
    exit /b 1
)

echo.
echo claude_fetch.exe built successfully in resources\
