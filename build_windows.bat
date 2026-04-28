@echo off
REM Windows Build Script for Remote Desktop Client
echo Building Remote Desktop Client for Windows...

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ and add it to your PATH
    pause
    exit /b 1
)

REM Check if Node.js is available
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed or not in PATH
    echo Please install Node.js 16+ and add it to your PATH
    pause
    exit /b 1
)

REM Check if Rust is available
cargo --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Rust is not installed or not in PATH
    echo Please install Rust from https://rustup.rs/
    pause
    exit /b 1
)

REM Navigate to project root
cd /d "%~dp0"

echo Installing Python dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo Building frontend...
cd desktop-client
call npm install
call npm run build
cd ..

echo Building Tauri application...
cd desktop-client\src-tauri
call cargo tauri build

echo.
echo Build completed!
echo Check the following directory for the installer:
echo desktop-client\src-tauri\target\release\bundle\nsis\
echo.
pause